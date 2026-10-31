import { Card } from "../../../../components/ui";
import { useProject } from "../shell";
import { SectionHead } from "../common";
import HostingPanel from "./HostingPanel";

/** صفحهٔ «انتشار روی اینترنت» در پروژه */
export default function HostingPage() {
  const { slug } = useProject();
  return (
    <Card>
      <div className="space-y-3">
        <SectionHead title="انتشار روی اینترنت" hint="سایتت را با یک نشانیِ ثابت یا دامنهٔ خودت روی اینترنت بگذار و پیام‌هایش را ببین." />
        <HostingPanel slug={slug} />
      </div>
    </Card>
  );
}
