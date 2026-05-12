import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Perfil" },
        ]}
        kicker="Client"
        title="Perfil"
        subtitle="Datos de la organización, equipo y preferencias."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Perfil" />
    </div>
  );
}
