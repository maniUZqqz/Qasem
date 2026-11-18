# چرخِ همراه (بدونِ اینترنت)

mv2code-2.3.0-py3-none-any.whl = بستهٔ pip ِ مخزنِ https://github.com/maniUZqqz/Machine-vision-TO-code ساخته‌شده از commit
ad3172221565414f2ea851bc7296c967f7bb30da (برچسبِ v2.3.0)؛ کدش کپی نشده، همان بستهٔ ساخته‌شده است. install-img2code.sh اول از همین نصب می‌کند.
بازساخت: git archive v2.3.0 | tar -x -C src/ && pip wheel --no-deps ./src   (sha256 در SHA256SUMS؛ چرخ بایت‌به‌بایت تکرارپذیر نیست چون زمانِ ساخت داخلش است).
مجوز: مخزن هنوز فایلِ LICENSE ندارد (مالکِ مخزن همان مالکِ NM است)؛ قلم‌های وزیرمتن و Inter داخلش با مجوزِ SIL OFL 1.1 هستند (فایلِ مجوزشان داخلِ چرخ است).
فهرستِ واژه‌های فارسیِ اصلاحِ OCR (`mv2code/data/fa_words.tsv.gz`، ۲۸ هزار واژه) از دادهٔ `wordfreq` است و مجوزِ **CC BY-SA 4.0** دارد (`mv2code/data/NOTICE.md` داخلِ چرخ)؛
فایلِ دادهٔ جداست و کد فقط می‌خواندش.
