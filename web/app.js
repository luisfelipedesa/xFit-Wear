const address = window.XFIT_DASHBOARD_URL;
if (address) {
  try {
    const target = new URL(address);
    if (target.protocol === "https:" && !target.username && !target.password) {
      const link = document.getElementById("dashboard");
      link.href = target.href;
      link.hidden = false;
      document.getElementById("status").textContent = "Acesso público ao dashboard com dados demonstrativos.";
    }
  } catch {
    document.getElementById("status").textContent = "Endereço do dashboard indisponível.";
  }
}
