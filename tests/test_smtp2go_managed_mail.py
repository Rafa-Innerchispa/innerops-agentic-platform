import io
import json
import urllib.error
from unittest.mock import MagicMock, call

import pytest
from pymongo.errors import DuplicateKeyError
from inneros_core_runtime.smtp2go_service import (
    ManagedMail, SMTP2GOClient, SMTP2GOError, READ_ENDPOINTS, WRITE_ENDPOINTS, redact,
)

KEY = 'api-' + 'A' * 32


def service():
    api, vault, db = MagicMock(), MagicMock(), MagicMock()
    db.__getitem__.return_value.find_one.return_value = {
        'client_id': 'acme', 'domain': 'example.com', 'subaccount_id': 'tenant-A',
        'smtp_username': 'inneros-acme-relay', 'smtp_password_key': 'acme_smtp_password',
    }
    return ManagedMail(api, vault, db), api, vault, db


@pytest.mark.parametrize('endpoint', [
    'subaccount/close', 'users/smtp/remove', 'domain/remove', '../subaccount/close',
    'https://attacker.example/email/send', 'api_keys/edit', 'api_keys/add', 'email/batch',
])
def test_forbidden_endpoints_never_touch_network(endpoint):
    network = MagicMock()
    with pytest.raises(PermissionError):
        SMTP2GOClient(KEY, transport=network).request(endpoint, apply=True)
    network.assert_not_called()


def test_provider_and_local_allowlists_have_no_destructive_operations():
    assert not any(p.rsplit('/', 1)[-1] in {'remove', 'delete', 'close'} for p in READ_ENDPOINTS | WRITE_ENDPOINTS)


def test_mutation_preview_has_no_network_or_password():
    network = MagicMock()
    result = SMTP2GOClient(KEY, transport=network).request('users/smtp/add', {'email_password': 'private', 'username': 'test'})
    assert result['dry_run'] is True
    assert 'private' not in json.dumps(result)
    network.assert_not_called()


def test_key_rejects_truncated_ui_values():
    with pytest.raises(ValueError):
        SMTP2GOClient('api-AAAA...')


def test_http_error_redacts_secrets_without_retrying():
    body = io.BytesIO(json.dumps({'error': KEY + ' private-password'}).encode())
    network = MagicMock(side_effect=urllib.error.HTTPError('https://api.smtp2go.com', 400, 'invalid', {}, body))
    with pytest.raises(SMTP2GOError) as exc:
        SMTP2GOClient(KEY, transport=network).request('users/smtp/add', {'email_password': 'private-password'}, apply=True)
    assert KEY not in str(exc.value)
    assert 'private-password' not in str(exc.value)
    assert network.call_count == 1


def test_mutation_timeout_is_not_retried_and_request_is_tls_verified():
    network = MagicMock(side_effect=TimeoutError(KEY))
    with pytest.raises(SMTP2GOError) as exc:
        SMTP2GOClient(KEY, transport=network).request('domain/add', {'domain': 'example.com'}, apply=True)
    assert network.call_count == 1
    assert KEY not in str(exc.value)
    context = network.call_args.kwargs['context']
    assert context.check_hostname is True
    assert context.verify_mode != 0


def test_successful_transport_keeps_key_in_header_not_url_or_body():
    response = MagicMock(); response.__enter__.return_value = io.BytesIO(b'{"request_id":"test","data":{}}')
    network = MagicMock(return_value=response)
    SMTP2GOClient(KEY, transport=network).request('domain/view', {'subaccount_id': 'tenant-A'})
    request = network.call_args.args[0]
    assert request.full_url == 'https://api.smtp2go.com/v3/domain/view'
    assert KEY not in request.full_url
    assert KEY.encode() not in request.data
    assert request.get_header('X-smtp2go-api-key') == KEY


def test_status_scopes_every_tenant_request_and_redacts_passwords():
    s, api, vault, db = service()
    api.request.side_effect = [
        {'data': {'subaccounts': [{'id': 'tenant-B'}, {'id': 'tenant-A'}]}},
        {'data': {'domains': []}}, {'data': {'results': [{'email_password': 'private'}]}},
    ]
    result = s.status('acme')
    assert result['account']['id'] == 'tenant-A'
    assert 'private' not in json.dumps(result)
    assert api.request.call_args_list[1:] == [call('domain/view', {'subaccount_id': 'tenant-A'}), call('users/smtp/view', {'subaccount_id': 'tenant-A'})]


def test_activity_uses_only_bound_subaccount_and_omits_headers():
    s, api, _, _ = service()
    s.activity('acme', limit=500)
    api.request.assert_called_once_with('activity/search', {'subaccounts': ['tenant-A'], 'limit': 100, 'include_headers': False})


def test_client_binding_cannot_be_reassigned():
    s, api, _, db = service()
    api.request.return_value = {'data': {'subaccounts': [{'id': 'tenant-B'}]}}
    with pytest.raises(PermissionError):
        s.register('acme', 'tenant-B', 'example.com', apply=True)
    db.__getitem__.return_value.update_one.assert_not_called()


def test_existing_smtp_user_without_vault_secret_is_not_rotated():
    s, api, vault, _ = service()
    api.request.return_value = {'data': {'results': [{'username': 'inneros-acme-relay'}]}}
    vault.get_owner_credential.return_value = {'ok': False}
    with pytest.raises(SMTP2GOError): s.ensure_smtp_user('acme', apply=True)
    assert api.request.call_count == 1
    vault.save_owner_credential.assert_not_called()


def test_vault_failure_prevents_user_creation():
    s, api, vault, _ = service()
    api.request.return_value = {'data': {'results': []}}
    vault.get_owner_credential.return_value = {'ok': False}
    vault.save_owner_credential.return_value = {'ok': False}
    with pytest.raises(SMTP2GOError): s.ensure_smtp_user('acme', apply=True)
    assert api.request.call_count == 1


def test_existing_provider_name_does_not_create_duplicate_account():
    s, api, _, db = service()
    db.__getitem__.return_value.find_one.return_value = None
    api.request.return_value = {'data': {'subaccounts': [{'id': 'old', 'name': ' ACME '}]}}
    with pytest.raises(SMTP2GOError): s.create_client('acme', 'Acme', 'example.com', cycle_limit=5000, apply=True)
    assert api.request.call_count == 1


def test_create_preview_has_no_paid_addons_or_invitation_email():
    s, api, _, db = service()
    db.__getitem__.return_value.find_one.return_value = None
    api.request.side_effect = [{'data': {'subaccounts': []}}, {'dry_run': True}]
    result = s.create_client('acme', 'Acme', 'example.com', cycle_limit=5000)
    payload = api.request.call_args.args[1]
    assert result['dry_run'] is True
    assert payload['fullname'] == 'Acme'
    assert payload['dedicated_ip'] is False and payload['archiving'] is False and payload['enable_sms'] is False
    assert 'subaccount_email' not in payload
    assert api.request.call_args.kwargs['apply'] is False


def test_conflicting_client_domain_is_rejected_before_provider_creation():
    s, api, _, db = service()
    db.__getitem__.return_value.find_one.side_effect = [None, {'client_id': 'someone-else'}]
    with pytest.raises(PermissionError): s.create_client('acme', 'Acme', 'example.com', cycle_limit=5000, apply=True)
    api.request.assert_not_called()


def test_generic_transport_error_does_not_expose_credentials():
    network = MagicMock(side_effect=OSError('request ' + KEY))
    with pytest.raises(SMTP2GOError) as exc: SMTP2GOClient(KEY, transport=network).request('domain/view')
    assert KEY not in str(exc.value)


def test_pending_provisioning_blocks_duplicate_external_mutation():
    s, api, _, db = service()
    db.__getitem__.return_value.find_one.return_value = None
    db.__getitem__.return_value.insert_one.side_effect = DuplicateKeyError('already pending')
    api.request.return_value = {'data': {'subaccounts': []}}
    with pytest.raises(SMTP2GOError):
        s.create_client('acme', 'Acme', 'example.com', cycle_limit=5000, apply=True)
    assert api.request.call_count == 1


def test_redaction_covers_nested_payloads_and_tokens_in_messages():
    result = redact({'nested': [{'secret': 'private', 'message': 'use ' + KEY}]})
    assert 'private' not in json.dumps(result)
    assert KEY not in json.dumps(result)
