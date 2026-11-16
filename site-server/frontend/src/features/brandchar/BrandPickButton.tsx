import { useState } from "react";

import { errorMessage } from "../../api/client";
import { Button, Spinner } from "../../components/ui";
import { bcApi } from "./api";

/** در انتخابگرِ عکسِ تامنیل‌ساز: «شخصیتِ برند» = استیکرِ شفافِ نیم‌تنهٔ شخصیتِ اصلی (بدونِ کارِ حذفِ پس‌زمینه). `resolve` عکسِ کتابخانه را در انتخابگر می‌نشاند. */
export default function BrandPickButton({ storeId, resolve, onError }: { storeId: string; resolve: (assetId: number) => Promise<void>; onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const r = await bcApi.useThumbnail(storeId, { pose: "thumbs_up" });
      await resolve(r.asset);
    } catch (e) {
      onError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button type="button" variant="secondary" size="sm" onClick={() => void go()} disabled={busy} data-testid="pick-brand-character">
      {busy ? <Spinner size={13} /> : null} شخصیتِ برند
    </Button>
  );
}
