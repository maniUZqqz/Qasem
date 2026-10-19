import { useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Button, Card, ErrorBox, PageHeader, Spinner } from "../../../components/ui";
import { errMsg, up3d } from "./api";
import { Muted, useToast } from "./shared";
import type { TokenInfo } from "./types";

/** توکنِ API ِ همین کاربر (rest_framework.authtoken) برای SDK، خطِ فرمان و curl. */
export default function TokenPage() {
  const toast = useToast();
  const [info, setInfo] = useState<TokenInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    up3d
      .token()
      .then(setInfo)
      .catch((e) => setError(errMsg(e)));
  }, []);

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast("کپی شد");
    } catch {
      toast("کپی نشد؛ دستی انتخاب کنید", true);
    }
  };

  if (!info) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const base = `${info.server}/api/v1/up3d`;
  const python = `from up3d.client import ApiClient\napi = ApiClient('${info.server}', '${info.token}')\nprint(api.get('/api/v1/up3d/video-projects/'))`;

  return (
    <div className="space-y-4">
      <PageHeader title="توکنِ API" subtitle={`کاربر: ${info.username}`} />
      <Card>
        <p className="text-sm" style={{ color: "var(--text-2)" }}>
          برای استفاده از API و SDK (کد) این توکن را در سرآیند بفرستید:
        </p>
        <div className="mt-2 flex items-start gap-2">
          <pre className="u3d-pre flex-1">Authorization: Token {info.token}</pre>
          <Button variant="secondary" size="sm" onClick={() => void copy(info.token)} title="کپیِ توکن">
            <Icon name="copy" size={14} />
            کپی
          </Button>
        </div>
        <Muted className="mt-3">نمونه:</Muted>
        <pre className="u3d-pre mt-1">{`curl -H "Authorization: Token ${info.token}" ${base}/assets/`}</pre>
        <pre className="u3d-pre mt-2">{python}</pre>
        <div className="mt-3">
          <Alert tone="warn">این توکن مثلِ رمزِ شماست؛ جایی منتشرش نکنید.</Alert>
        </div>
      </Card>
    </div>
  );
}
