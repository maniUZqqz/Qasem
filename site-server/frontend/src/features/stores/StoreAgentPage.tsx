import AgentSettingsCard from "../../components/AgentSettingsCard";
import { useStore } from "./StoreLayout";

/** قوانین ایجنت فروش — لحن، «همیشه بگو»، «هرگز نگو»، اجازه‌ی تخفیف. */
export default function StoreAgentPage() {
  return <AgentSettingsCard storeId={useStore().storeId} />;
}
