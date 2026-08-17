"""Toma todas las capturas del recorrido KYB Fase 8 y las guarda en
docs/kyb/manual_kyb/screenshots/. Reutilizable: se puede volver a correr
en cualquier momento para actualizar el manual."""
from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path("/app/docs/kyb/manual_kyb/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
BURL = "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com"


def login(ctx, email):
    p = ctx.new_page()
    p.set_default_timeout(30000)
    p.goto(f"{BURL}/api/v1/auth/dev-login?email={email}")
    p.wait_for_load_state("networkidle")
    return p


def snap(page, name):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"  ✓ {name}")


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/root/bin/chromium",
                              args=["--no-sandbox"])

        # ===== Cliente (Cliente A - wizard en blanco) =====
        c = b.new_context(viewport={"width": 1440, "height": 900})
        pg = login(c, "cliente-a-phase8@preview-prosper.io")

        pg.goto(f"{BURL}/kyb/onboarding")
        pg.wait_for_timeout(2500)
        snap(pg, "01_client_wizard_tax")

        # Sección Equipo (colapsada)
        pg.click("text=Gestioná tu equipo")
        pg.wait_for_timeout(1500)
        snap(pg, "02_client_team_collapsed")

        # Sección Equipo con form expandido
        pg.click("summary:has-text('Invitar miembro')")
        pg.wait_for_timeout(800)
        # completar campos para que se vean con datos
        pg.fill("[data-testid=kyb-team-invite-tax-id]", "30712345675")
        pg.fill("[data-testid=kyb-team-invite-email]", "contador@estudio.io")
        pg.click("[data-testid=kyb-team-invite-role-operator]")
        pg.wait_for_timeout(600)
        snap(pg, "03_client_team_form_filled")

        # Modal Compartir link
        pg.click("text=Compartir link de acceso")
        pg.wait_for_timeout(1200)
        snap(pg, "04_client_share_modal_empty")

        # Generar y capturar
        pg.click("[data-testid=kyb-share-create-button]")
        pg.wait_for_timeout(2000)
        snap(pg, "05_client_share_modal_created")
        shared_url = pg.eval_on_selector("[data-testid=kyb-share-issued-url]",
                                         "el => el.value")
        print(f"  URL compartida: {shared_url}")
        c.close()

        # ===== Público sin sesión =====
        c_pub = b.new_context(viewport={"width": 1440, "height": 900})
        pg = c_pub.new_page()
        pg.set_default_timeout(30000)
        pg.goto(shared_url)
        pg.wait_for_load_state("networkidle")
        pg.wait_for_timeout(2000)
        snap(pg, "06_public_shared_upload")
        c_pub.close()

        # ===== Aceptación de invitación pública =====
        c_acc = b.new_context(viewport={"width": 1440, "height": 900})
        pg = c_acc.new_page()
        pg.goto(f"{BURL}/kyb/team/accept?token=demoTOKEN")
        pg.wait_for_timeout(2000)
        snap(pg, "07_public_team_accept")
        c_acc.close()

        # ===== Admin (super_admin) =====
        c_adm = b.new_context(viewport={"width": 1440, "height": 900})
        pg = login(c_adm, "super@prosper.foundation")

        pg.goto(f"{BURL}/admin/compliance/kyb")
        pg.wait_for_timeout(2500)
        snap(pg, "08_admin_tray")

        # Detalle - Expediente (default)
        pg.goto(f"{BURL}/admin/compliance/kyb/kyb_574f214108df")
        pg.wait_for_timeout(3000)
        snap(pg, "09_admin_detail_expediente")

        for tab, name in [("Beneficiarios", "10_admin_ubos"),
                          ("Documentos", "11_admin_documents"),
                          ("Verificaciones", "12_admin_verifications"),
                          ("Verificación manual", "13_admin_manual_checks"),
                          ("Screening", "14_admin_screening"),
                          ("Registro", "15_admin_registry"),
                          ("Riesgo", "16_admin_risk"),
                          ("Auditoría", "17_admin_audit")]:
            try:
                pg.click(f"button:has-text('{tab}')", timeout=5000)
                pg.wait_for_timeout(1500)
                snap(pg, name)
            except Exception as e:
                print(f"  ! tab {tab}: {e}")

        # Settings
        pg.goto(f"{BURL}/admin/compliance/kyb/settings/providers")
        pg.wait_for_timeout(2500)
        snap(pg, "18_settings_providers")

        pg.goto(f"{BURL}/admin/compliance/kyb/settings/risk-model")
        pg.wait_for_timeout(2500)
        snap(pg, "19_settings_risk_model")

        # Templates
        pg.goto(f"{BURL}/admin/compliance/kyb/templates")
        pg.wait_for_timeout(2500)
        snap(pg, "20_settings_templates")

        c_adm.close()
        b.close()
    print("Listo.")


if __name__ == "__main__":
    main()
