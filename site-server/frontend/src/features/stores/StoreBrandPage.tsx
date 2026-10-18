import { FormEvent, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Button, Card, Field, Input, SectionTitle, TextArea } from "../../components/ui";
import { useStore } from "./StoreLayout";

/** پروفایل برند — لحن، قوانین، و اطلاعات پرداخت. */
export default function StoreBrandPage() {
  const { profile, setProfile, storeId, setError, setNotice } = useStore();
  const [busy, setBusy] = useState(false);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.patch(`/stores/${storeId}/profile/`, {
        brand_voice: profile.brand_voice,
        tone: profile.tone,
        shipping_policy: profile.shipping_policy,
        return_policy: profile.return_policy,
        payment_info: profile.payment_info,
      });
      setNotice("پروفایل برند ذخیره شد.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Alert tone="brand" title="این صفحه ورودی هر متنی است که AI می‌نویسد">
        لحن و صدای برند در پرامپت کپشن، سناریو و جواب ایجنت فروش می‌رود. خالی گذاشتنش
        یعنی خروجی شبیه بقیه‌ی فروشگاه‌ها می‌شود.
      </Alert>

      <Card>
        <SectionTitle>هویت برند</SectionTitle>
        <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
          <Field label="لحن برند">
            <Input
              value={profile.tone}
              onChange={(e) => setProfile({ ...profile, tone: e.target.value })}
              placeholder="مثلاً صمیمی، رسمی، لوکس…"
            />
          </Field>
          <Field label="صدای برند">
            <Input
              value={profile.brand_voice}
              onChange={(e) => setProfile({ ...profile, brand_voice: e.target.value })}
            />
          </Field>
          <Field label="قوانین ارسال">
            <TextArea
              rows={2}
              value={profile.shipping_policy}
              onChange={(e) => setProfile({ ...profile, shipping_policy: e.target.value })}
            />
          </Field>
          <Field label="قوانین مرجوعی">
            <TextArea
              rows={2}
              value={profile.return_policy}
              onChange={(e) => setProfile({ ...profile, return_policy: e.target.value })}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field
              label="اطلاعات پرداخت"
              hint="ایجنت فروش عیناً همین متن را به مشتری می‌دهد — پس همان‌طور بنویسید که می‌خواهید مشتری بخواند."
            >
              <TextArea
                rows={2}
                value={profile.payment_info}
                onChange={(e) => setProfile({ ...profile, payment_info: e.target.value })}
                placeholder="مثلاً: کارت 6037-99XX-XXXX-1234 بانک ملی به نام … — بعد از واریز، رسید را در چت بفرستید."
              />
            </Field>
          </div>
          <div>
            <Button type="submit" disabled={busy}>
              <Icon name="check" size={15} />
              {busy ? "در حال ذخیره…" : "ذخیره پروفایل"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
