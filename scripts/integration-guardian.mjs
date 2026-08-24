const PROTECTED_BRANCHES = new Set(['main', 'master', 'production']);
const DOC_EXTENSIONS = ['.md', '.mdx', '.txt'];
const GENERATED_PREFIXES = ['node_modules/', 'dist/', 'coverage/', '.next/', 'build/'];

export function evaluateEvidence(input = {}) {
  const branch = String(input.branch || '').trim();
  const changedFiles = Array.isArray(input.changedFiles) ? input.changedFiles.map(String) : [];
  const taskKind = String(input.taskKind || 'development');
  const testCommand = String(input.testCommand || '').trim();
  const testExitCode = Number.isInteger(input.testExitCode) ? input.testExitCode : null;
  const skippedTests = Number.isFinite(input.skippedTests) ? Number(input.skippedTests) : 0;
  const failures = [];

  if (!branch) failures.push('branch_missing');
  if (PROTECTED_BRANCHES.has(branch)) failures.push('protected_branch_direct_work');
  if (!changedFiles.length) failures.push('no_changed_files');

  const generated = changedFiles.filter((file) => GENERATED_PREFIXES.some((prefix) => file.startsWith(prefix)));
  if (generated.length) failures.push(`generated_artifacts:${generated.join(',')}`);

  if (taskKind === 'development' && changedFiles.length) {
    const docsOnly = changedFiles.every((file) => DOC_EXTENSIONS.some((ext) => file.toLowerCase().endsWith(ext)));
    if (docsOnly) failures.push('docs_only_development_output');
  }

  if (taskKind === 'development' || taskKind === 'verification') {
    if (!testCommand) failures.push('tests_missing');
    if (testExitCode === null) failures.push('test_exit_code_missing');
    else if (testExitCode !== 0) failures.push(`tests_failed:${testExitCode}`);
    if (skippedTests > 0) failures.push(`tests_skipped:${skippedTests}`);
  }

  const hasTestFile = changedFiles.some((file) => /(^|\/)(tests?|__tests__)\//i.test(file) || /\.(test|spec)\.[cm]?[jt]sx?$/i.test(file));
  if (taskKind === 'development' && !hasTestFile) failures.push('test_evidence_file_missing');

  return {
    ok: failures.length === 0,
    gate: failures.length === 0 ? 'PASS' : 'REJECT',
    branch,
    changedFiles,
    failures,
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const raw = process.argv[2] || '{}';
  let payload;
  try { payload = JSON.parse(raw); }
  catch { console.error(JSON.stringify({ ok:false, gate:'REJECT', failures:['invalid_json'] })); process.exit(2); }
  const result = evaluateEvidence(payload);
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}
