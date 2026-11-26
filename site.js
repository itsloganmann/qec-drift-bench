const auditUrl = "https://raw.githubusercontent.com/itsloganmann/quantum-bench/main/data/audits/codex-replication-progress.json";

async function refreshAudit() {
  const response = await fetch(auditUrl, { credentials: "omit", signal: AbortSignal.timeout(6000) });
  if (!response.ok) return;

  const audit = await response.json();
  const completed = audit.completed_evaluations;
  const planned = audit.planned_evaluations;
  if (typeof audit.checked_utc !== "string") return;
  const auditedAt = new Date(audit.checked_utc);

  if (
    !Number.isSafeInteger(completed) ||
    !Number.isSafeInteger(planned) ||
    completed < 0 ||
    planned < 1 ||
    completed > planned ||
    Number.isNaN(auditedAt.getTime())
  ) return;

  const format = new Intl.NumberFormat("en-US");
  const date = new Intl.DateTimeFormat("en-US", { dateStyle: "long", timeZone: "UTC" });
  const progress = document.getElementById("progress");
  document.getElementById("completed").textContent = format.format(completed);
  document.getElementById("planned").textContent = format.format(planned);
  document.getElementById("audit-date").textContent = "Audit from " + date.format(auditedAt);
  progress.max = planned;
  progress.value = completed;
}

refreshAudit().catch(() => undefined);
