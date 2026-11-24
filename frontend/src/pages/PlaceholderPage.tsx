import { useTranslation } from "react-i18next";
import { Card, PageHeader } from "@/components/ui";

export function PlaceholderPage({ titleKey }: { titleKey: string }) {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t(titleKey)} />
      <Card>
        <p className="text-sm text-zinc-500">{t("common.comingSoon")}</p>
      </Card>
    </>
  );
}
