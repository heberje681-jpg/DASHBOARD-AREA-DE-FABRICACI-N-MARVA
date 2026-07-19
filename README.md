# Dashboard de Piso — Marva Silos y Construcción

Dashboard en tiempo real conectado a Odoo (vía XML-RPC) para la oficina
de producción/fabricación. Muestra órdenes activas, avance, carga por
centro de trabajo, horas planeadas vs. reales, costos (materiales +
mano de obra) y alertas de calidad.

## 1. Prueba local

```bash
pip install -r requirements.txt
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # llena tus credenciales
streamlit run dashboard_marva.py
```

## 2. Subir a GitHub

1. Crea un **repositorio privado** en GitHub (importante: privado, porque
   aunque las credenciales de Odoo no van en el código, no hay razón para
   exponer la lógica del dashboard públicamente).
2. Sube todo excepto `.streamlit/secrets.toml` (el `.gitignore` ya lo
   excluye automáticamente):

```bash
git init
git add .
git commit -m "Dashboard de piso - Marva"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/marva-dashboard.git
git push -u origin main
```

## 3. Desplegar en Streamlit Community Cloud (gratis)

1. Entra a https://share.streamlit.io con tu cuenta de GitHub.
2. "New app" → selecciona el repo `marva-dashboard`, branch `main`,
   archivo principal `dashboard_marva.py`.
3. Antes de darle "Deploy", ve a **Advanced settings → Secrets** y pega
   el contenido de tu `secrets.toml` real (ODOO_URL, ODOO_DB, ODOO_USER,
   ODOO_PASSWORD). Streamlit Cloud lo guarda cifrado, nunca queda en el
   repo público.
4. Deploy. Te da un link tipo `https://marva-dashboard.streamlit.app`
   que puedes compartir con Valerio — funciona en cualquier navegador,
   sin instalar nada, y se actualiza solo.

### Nota de seguridad
- Si el servidor de Odoo de Marva no es accesible desde internet (solo
  red local/VPN), Streamlit Cloud no podrá conectarse. En ese caso hay
  dos opciones: (a) exponer el endpoint XML-RPC de Odoo de forma segura
  (HTTPS + firewall a IPs específicas), o (b) correr este dashboard en
  una máquina dentro de la misma red que Odoo (por ejemplo la
  computadora de Valerio, con `streamlit run` en segundo plano, o un
  mini-servidor local).
- Usa un usuario de Odoo dedicado para esta integración, con permisos
  de **solo lectura** sobre Manufactura, Inventario y Calidad — así el
  dashboard nunca puede modificar nada en Odoo aunque alguien
  intercepte las credenciales.
