// Turnix usa HTML estatico (paciente.html, medico.html, acceso.html) en /public
// El bundle React no se renderiza para no interferir con esos archivos.
const root = document.getElementById("root");
if (root) {
  // Evita pantalla en blanco si alguien navega al "/" sin que index.html se cargue.
  root.innerHTML = "";
}
