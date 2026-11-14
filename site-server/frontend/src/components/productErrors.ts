import axios from "axios";

import { errorMessage } from "../api/client";
import { fieldErrorSentence } from "./numberInput";

/**
 * خطای ذخیره‌ی محصول (قیمت، موجودی …) به جمله‌ی فارسی.
 *
 * `errorMessage` برای خطای فیلد می‌نویسد «price: …» — نامِ انگلیسیِ فیلد جلوی
 * جمله. اینجا اگر سرور درباره‌ی یکی از فیلدهای عددی حرف زده، همان جمله می‌آید
 * (سرور فارسی و با نامِ فیلد می‌نویسد)؛ وگرنه همان `errorMessage`.
 */
export function productErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const sentence = fieldErrorSentence(err.response?.data);
    if (sentence) return sentence;
  }
  return errorMessage(err);
}
