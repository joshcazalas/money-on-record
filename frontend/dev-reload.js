// This endpoint exists only in tools/dev.py. Static hosting needs no dev server.
if (["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) {
  let previous;
  let checking = false;
  setInterval(async () => {
    if (checking || document.hidden) return;
    checking = true;
    try {
      const response = await fetch("/__dev/revision", { cache: "no-store" });
      if (!response.ok) return;
      const { revision } = await response.json();
      if (previous && previous !== revision) location.reload();
      previous = revision;
    } catch { /* Keep the current page usable while the server restarts. */ }
    finally { checking = false; }
  }, 900);
}
