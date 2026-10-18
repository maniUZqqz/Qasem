import AIStatusCard from "../../components/AIStatusCard";
import DataPolicyCard from "../../components/DataPolicyCard";
import EmbeddingsCard from "../../components/EmbeddingsCard";
import { useStore } from "./StoreLayout";

/** سیاست داده و وضعیت موتورهای AI — کجا داده‌ی این فروشگاه پردازش می‌شود. */
export default function StoreDataPage() {
  const { storeId } = useStore();
  return (
    <div className="space-y-5">
      <DataPolicyCard storeId={storeId} />
      <AIStatusCard />
      <EmbeddingsCard storeId={storeId} />
    </div>
  );
}
