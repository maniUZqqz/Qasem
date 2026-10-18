import MembersCard from "../../components/MembersCard";
import ReferralCard from "../../components/ReferralCard";
import { useStore } from "./StoreLayout";

/** اعضای فروشگاه و دعوت — شش نقش با دسترسی‌های جدا. */
export default function StoreTeamPage() {
  const { storeId } = useStore();
  return (
    <div className="space-y-5">
      <MembersCard storeId={storeId} />
      <ReferralCard storeId={storeId} />
    </div>
  );
}
