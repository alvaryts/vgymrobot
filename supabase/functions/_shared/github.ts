export async function dispatchGitHubWorker(requestId: string): Promise<void> {
  const token = Deno.env.get("GITHUB_WORKFLOW_TOKEN");
  const owner = Deno.env.get("GITHUB_OWNER");
  const repo = Deno.env.get("GITHUB_REPO");
  const workflowId = Deno.env.get("GITHUB_WORKFLOW_ID") ?? "remote-worker.yml";
  const ref = Deno.env.get("GITHUB_REF") ?? "main";

  if (!token || !owner || !repo) {
    throw new Error("Faltan secretos GitHub para disparar el worker");
  }

  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowId}/dispatches`,
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          request_id: requestId,
        },
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`No se pudo disparar GitHub Actions: ${response.status} ${body}`);
  }
}
