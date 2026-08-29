from __future__ import annotations

from inneros_core_runtime import local_model_manager


def test_runtime_versions_prefers_active_docker_container(monkeypatch):
    calls = []

    def fake_node_run(node, argv, *, timeout=30):
        calls.append(argv)
        command = " ".join(argv)
        if "docker exec" in command:
            return {
                "ok": True,
                "stdout": "container=inneros-vllm-canary-rocm10\n"
                "python=/opt/python/bin/python\n"
                "torch_version=2.11.0+rocm7.14.0\n"
                "torch_hip=7.14.60850\n"
                "vllm_version=0.23.1.dev1+rocm714\n",
                "stderr": "",
                "returncode": 0,
            }
        if "docker inspect" in command:
            return {"ok": True, "stdout": "name=/inneros-vllm-canary-rocm10 image=rocm/vllm pid=123 args=[]\n", "stderr": "", "returncode": 0}
        return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}

    monkeypatch.setattr(local_model_manager, "_node_run", fake_node_run)

    versions = local_model_manager._runtime_versions("amd")

    assert versions["vllm_source"] == "docker_active_container"
    assert "rocm7.14" in versions["vllm"]["stdout"]
    assert "vllm-rocm" not in versions["vllm"]["stdout"]
