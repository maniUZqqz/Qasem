/**
 * زیرصفحه‌های محصول.
 *
 * هرکدام یک پنل موجود را می‌گیرد و محصول را از قاب به آن می‌دهد. پنل‌ها
 * دست‌نخورده‌اند — کاری که اینجا شد، *کجا* رندر شدنشان بود نه *چه* بودنشان.
 */
import IntelligencePanel from "../ai/IntelligencePanel";
import MarketPanel from "../ai/MarketPanel";
import AdvancedModePanel from "../content/AdvancedModePanel";
import CaptionsPanel from "../content/CaptionsPanel";
import ImageStudioPanel from "../content/ImageStudioPanel";
import VideoStudioPanel from "../content/VideoStudioPanel";
import { useProduct } from "./ProductLayout";

export function IntelligenceTab() {
  return <IntelligencePanel productId={useProduct().product.id} />;
}

export function MarketTab() {
  return <MarketPanel productId={useProduct().product.id} />;
}

export function ImagesTab() {
  return <ImageStudioPanel product={useProduct().product} />;
}

export function CaptionsTab() {
  return <CaptionsPanel productId={useProduct().product.id} />;
}

export function VideoTab() {
  const { product } = useProduct();
  return <VideoStudioPanel productId={product.id} storeId={product.store} />;
}

export function AdvancedTab() {
  return <AdvancedModePanel productId={useProduct().product.id} />;
}
