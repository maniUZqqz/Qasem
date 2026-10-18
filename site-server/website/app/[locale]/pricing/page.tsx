import type { Metadata } from "next";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { notFound } from "next/navigation";

import { breadcrumbs, faqPage, offers } from "@/lib/seo";
import { getFaqGroups } from "@/lib/faq";
import { TEAM_COST, contentFor } from "@/lib/content";
import { getSite } from "@/lib/site";
import { alternatesFor, isLocale, LOCALES, type Locale } from "@/lib/i18n";
import { getPlans, money, num } from "@/lib/plans";
import { COPY } from "./copy";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].metaTitle,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/pricing"),
  };
}

// prices are read from the running backend; five minutes is fresh enough for
// a marketing page and keeps the site up if the API blips
export const revalidate = 300;

export default async function Pricing({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { faq: fallbackFaq, trust } = contentFor(l);
  // `faq.slice(6, 9)` used to pick these — three questions identified by their
  // position in a list, so inserting one anywhere above silently changed which
  // questions the pricing page asks. They are the «قیمت» group now.
  const groups = await getFaqGroups(l);
  const faq =
    groups.find((g) => g.key === "PRICING")?.items ?? fallbackFaq.slice(6, 9);
  const site = await getSite(l);
  const fa = (v: number | string) => num(v, l);
  const toman = (v: number) => money(v, l);

  const { plans, live } = await getPlans();
  const paid = plans.filter((p) => !p.is_trial);

  return (
    <>
      <JsonLd
        data={[
          breadcrumbs([{ name: c.crumb, path: "/pricing" }], l),
          offers(paid),
          faqPage(faq),
        ]}
      />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1"
            eyebrow={c.eyebrow}
            title={c.title}
            lead={c.lead}
          />

          <div className="grid g3 in-view-stagger" style={{ marginTop: 48, alignItems: "start" }}>
            {paid.map((plan) => {
              const featured = plan.slug === "pro";
              const saving = TEAM_COST - plan.price_toman;
              return (
                <div
                  key={plan.slug}
                  id={plan.slug}
                  className={`card card-hover plan ${featured ? "plan-featured" : ""}`}
                >
                  {featured && <span className="eyebrow plan-tag">{c.recommended}</span>}

                  <h3 style={{ fontSize: "1.25rem" }}>{plan.name}</h3>

                  <div className="plan-price">
                    <span className={`v num ${featured ? "gradient-text" : ""}`}>
                      {toman(plan.price_toman)}
                    </span>
                    <span className="muted">{c.perMonth}</span>
                  </div>

                  <ul className="checks mt-md">
                    <Item>{c.videoSeconds(fa(plan.video_seconds))}</Item>
                    <Item>{c.images(fa(plan.images))}</Item>
                    <Item>{c.captions(fa(plan.captions))}</Item>
                    <Item>{c.analysis}</Item>
                    {plan.allows_sales_agent && <Item>{c.salesAgent}</Item>}
                    {plan.allows_publishing && <Item>{c.publishing}</Item>}
                    <Item>
                      {plan.max_products === 0
                        ? c.unlimitedProducts
                        : c.upToProducts(fa(plan.max_products))}
                    </Item>
                  </ul>

                  <a
                    href={`${site.panelUrl}/register?plan=${plan.slug}`}
                    className={featured ? "btn btn-primary" : "btn btn-ghost"}
                    style={{ marginTop: 24, width: "100%", justifyContent: "center" }}
                  >
                    {c.twoWeeksFree}
                  </a>

                  <p className="muted center mt">
                    {c.cheaperThan(toman(saving))}
                  </p>
                </div>
              );
            })}
          </div>

          <p className="muted center mt-md">
            {c.allPlansStart}
            <b style={{ color: "var(--text-2)" }}>{c.twoWeeksFree}</b>
            {c.allPlansEnd}
            {!live && c.stale}
          </p>
        </div>
      </section>

      {/* --------------------------------------------- plan side by side */}
      <section className="section-soft">
        <div className="wrap">
          <SectionHead eyebrow={c.cmpEyebrow} title={c.cmpTitle} />
          <div className="card mt-lg" style={{ overflowX: "auto" }}>
            <table className="cmp">
              <thead>
                <tr>
                  <Th>{c.monthlyQuota}</Th>
                  {paid.map((p) => (
                    <Th key={p.slug} highlight={p.slug === "pro"}>{p.name}</Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="label">{c.rowVideo}</td>
                  {paid.map((p) => (
                    <td key={p.slug} className={p.slug === "pro" ? "win" : ""}>
                      {fa(p.video_seconds)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="label">{c.rowImages}</td>
                  {paid.map((p) => (
                    <td key={p.slug} className={p.slug === "pro" ? "win" : ""}>
                      {fa(p.images)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="label">{c.rowCaptions}</td>
                  {paid.map((p) => (
                    <td key={p.slug} className={p.slug === "pro" ? "win" : ""}>
                      {fa(p.captions)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="label">{c.rowProducts}</td>
                  {paid.map((p) => (
                    <td key={p.slug} className={p.slug === "pro" ? "win" : ""}>
                      {p.max_products === 0 ? c.unlimited : fa(p.max_products)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="label">{c.rowAgent}</td>
                  {paid.map((p) => (
                    <td key={p.slug}>{p.allows_sales_agent ? "✔" : "—"}</td>
                  ))}
                </tr>
                <tr>
                  <td className="label">{c.rowPublishing}</td>
                  {paid.map((p) => (
                    <td key={p.slug}>{p.allows_publishing ? "✔" : "—"}</td>
                  ))}
                </tr>
                <tr>
                  <td className="label">{c.rowAnalysis}</td>
                  {paid.map((p) => (
                    <td key={p.slug}>✔</td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ comparison */}
      <section>
        <div className="wrap">
          <SectionHead
            eyebrow={c.vsEyebrow}
            title={c.vsTitle}
            lead={c.vsLead(toman(TEAM_COST))}
          />
          <div className="card mt-lg" style={{ overflowX: "auto" }}>
            <table className="cmp">
              <thead>
                <tr>
                  <Th>{c.colItem}</Th>
                  <Th>{c.colTeam}</Th>
                  <Th>{c.colAgency}</Th>
                  <Th highlight>{c.colUs}</Th>
                </tr>
              </thead>
              <tbody>
                <Row label={c.vsRows.cost} a={`${toman(TEAM_COST)}+`} b={c.vsRows.unclear} c={c.vsRows.from(toman(paid[0]?.price_toman ?? 0))} />
                <Row label={c.vsRows.firstOutput} a={c.vsRows.weeks} b={c.vsRows.days} c={c.vsRows.sameSession} />
                <Row label={c.vsRows.expertise} a={c.vsRows.manageTeam} b={c.vsRows.manageContract} c={c.vsRows.none} />
                <Row label={c.vsRows.control} a={c.vsRows.full} b={c.vsRows.low} c={c.vsRows.fullYours} />
                <Row label={c.vsRows.salesSupport} a={c.vsRows.separateAdmin} b={c.vsRows.usuallyNot} c={c.vsRows.included} />
                <Row label={c.vsRows.competitor} a={c.vsRows.manual} b={c.vsRows.sometimes} c={c.vsRows.autoWeb} />
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------- trust */}
      <section className="section-soft">
        <div className="wrap">
          <div className="grid g4 in-view-stagger">
            {trust.map((x) => (
              <div key={x.title} className="card">
                <div className="icon-lg">{x.icon}</div>
                <h3 className="mt-sm">{x.title}</h3>
                <p className="muted mt-sm">{x.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------- faq */}
      <section className="section-soft">
        <div className="wrap wrap-md">
          <SectionHead title={c.faqTitle} />
          <div className="stack-sm mt-md">
            {faq.map((f: { q: string; a: string }) => (
              <details key={f.q} className="card qa">
                <summary>{f.q}</summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <div className="cta-band">
            <h2>{c.ctaTitle}</h2>
            <p className="lead mt narrower">
{c.ctaLead}
            </p>
            <div className="row mt-md center-row">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                شروع رایگان ←
              </a>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

function Item({ children }: { children: React.ReactNode }) {
  return <li>{children}</li>;
}

function Th({ children, highlight }: { children: React.ReactNode; highlight?: boolean }) {
  return <th className={highlight ? "win" : ""}>{children}</th>;
}

function Row({ label, a, b, c }: { label: string; a: string; b: string; c: string }) {
  return (
    <tr>
      <td className="label">{label}</td>
      <td>{a}</td>
      <td>{b}</td>
      <td className="win">{c}</td>
    </tr>
  );
}
