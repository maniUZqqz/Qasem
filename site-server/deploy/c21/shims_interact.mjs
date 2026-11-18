// Interactive primitives (round 5, 2026-11-18).
//
// A static render shows only the OPEN accordion item / the ACTIVE tab: the other answers were not in the HTML at all (the FAQ of Chagher showed one answer and four dead rows, and the
// collapsed texts could not even be edited). These stand-ins render EVERY panel (closed ones carry the `hidden` attribute) and mark the parts with data-nbc-* so the tiny runtime
// (backend/apps/projects/builder/c21_runtime.py) can open/close them on the published site. Same props as Radix (value/defaultValue/type/asChild ...), written from scratch (our own code).
// Base UI (@base-ui/react, MIT) stays the real library with `keepMounted` forced on, so its closed panels are in the HTML as well.
//
// convert.mjs resolves these specifiers to the sources below (namespace "nbc"); the real packages stay reachable as "<specifier>?real".
const NBC_HEAD = `import * as React from 'react'; import { Slot } from '@radix-ui/react-slot';
const arr = (v) => (v == null || v === '' ? [] : Array.isArray(v) ? v : [v]);
const st = (on) => (on ? 'open' : 'closed');`;

const NBC_ACCORDION = `${NBC_HEAD}
const Ctx = React.createContext({ on: () => false });
const ItemCtx = React.createContext({ on: false });
export const Root = React.forwardRef(function Root({ type = 'single', value, defaultValue, collapsible, onValueChange, dir, disabled, orientation = 'vertical', asChild, children, ...rest }, ref) {
  const open = arr(value !== undefined ? value : defaultValue); const C = asChild ? Slot : 'div';
  return <Ctx.Provider value={{ on: (v) => open.includes(v) }}><C ref={ref} data-orientation={orientation} data-nbc-acc={type === 'multiple' ? 'multiple' : 'single'} {...rest}>{children}</C></Ctx.Provider>;
});
export const Item = React.forwardRef(function Item({ value, disabled, asChild, children, ...rest }, ref) {
  const on = React.useContext(Ctx).on(value); const C = asChild ? Slot : 'div';
  return <ItemCtx.Provider value={{ on }}><C ref={ref} data-state={st(on)} data-orientation="vertical" data-nbc-item="" {...rest}>{children}</C></ItemCtx.Provider>;
});
export const Header = React.forwardRef(function Header({ asChild, children, ...rest }, ref) {
  const on = React.useContext(ItemCtx).on; const C = asChild ? Slot : 'h3';
  return <C ref={ref} data-state={st(on)} data-orientation="vertical" data-nbc-head="" {...rest}>{children}</C>;
});
export const Trigger = React.forwardRef(function Trigger({ asChild, children, ...rest }, ref) {
  const on = React.useContext(ItemCtx).on; const C = asChild ? Slot : 'button';
  return <C ref={ref} type="button" aria-expanded={on} data-state={st(on)} data-orientation="vertical" data-nbc-trigger="" {...rest}>{children}</C>;
});
export const Content = React.forwardRef(function Content({ asChild, forceMount, children, ...rest }, ref) {
  const on = React.useContext(ItemCtx).on; const C = asChild ? Slot : 'div';
  return <C ref={ref} role="region" data-state={st(on)} data-orientation="vertical" hidden={!on} data-nbc-panel="" {...rest}>{children}</C>;
});
export const Accordion = Root; export const AccordionItem = Item; export const AccordionHeader = Header; export const AccordionTrigger = Trigger; export const AccordionContent = Content; export default Root;`;

const NBC_COLLAPSIBLE = `${NBC_HEAD}
const Ctx = React.createContext({ on: false });
export const Root = React.forwardRef(function Root({ open, defaultOpen, onOpenChange, disabled, asChild, children, ...rest }, ref) {
  const on = !!(open !== undefined ? open : defaultOpen); const C = asChild ? Slot : 'div';
  return <Ctx.Provider value={{ on }}><C ref={ref} data-state={st(on)} data-nbc-root="" {...rest}>{children}</C></Ctx.Provider>;
});
export const Trigger = React.forwardRef(function Trigger({ asChild, children, ...rest }, ref) {
  const on = React.useContext(Ctx).on; const C = asChild ? Slot : 'button';
  return <C ref={ref} type="button" aria-expanded={on} data-state={st(on)} data-nbc-trigger="" {...rest}>{children}</C>;
});
export const Content = React.forwardRef(function Content({ asChild, forceMount, children, ...rest }, ref) {
  const on = React.useContext(Ctx).on; const C = asChild ? Slot : 'div';
  return <C ref={ref} data-state={st(on)} hidden={!on} data-nbc-panel="" {...rest}>{children}</C>;
});
export const Collapsible = Root; export const CollapsibleTrigger = Trigger; export const CollapsibleContent = Content; export default Root;`;

const NBC_TABS = `${NBC_HEAD}
const Ctx = React.createContext({ value: undefined });
export const Root = React.forwardRef(function Root({ value, defaultValue, onValueChange, orientation = 'horizontal', dir, activationMode, asChild, children, ...rest }, ref) {
  const C = asChild ? Slot : 'div';
  return <Ctx.Provider value={{ value: value !== undefined ? value : defaultValue }}><C ref={ref} dir={dir} data-orientation={orientation} {...rest}>{children}</C></Ctx.Provider>;
});
export const List = React.forwardRef(function List({ loop, asChild, children, ...rest }, ref) {
  const C = asChild ? Slot : 'div';
  return <C ref={ref} role="tablist" aria-orientation="horizontal" data-orientation="horizontal" {...rest}>{children}</C>;
});
export const Trigger = React.forwardRef(function Trigger({ value, disabled, asChild, children, ...rest }, ref) {
  const on = React.useContext(Ctx).value === value; const C = asChild ? Slot : 'button';
  return <C ref={ref} type="button" role="tab" aria-selected={on} data-state={on ? 'active' : 'inactive'} data-orientation="horizontal" tabIndex={on ? 0 : -1} data-nbc-tab="" {...rest}>{children}</C>;
});
export const Content = React.forwardRef(function Content({ value, forceMount, asChild, children, ...rest }, ref) {
  const on = React.useContext(Ctx).value === value; const C = asChild ? Slot : 'div';
  return <C ref={ref} role="tabpanel" data-state={on ? 'active' : 'inactive'} data-orientation="horizontal" hidden={!on} tabIndex={0} data-nbc-tabpanel="" {...rest}>{children}</C>;
});
export const Tabs = Root; export const TabsList = List; export const TabsTrigger = Trigger; export const TabsContent = Content; export default Root;`;

// Base UI: the real part (Panel) forced to keepMounted, everything else untouched
const baseWrap = (sub, name) => `export * from '${sub}?real';
import { ${name} as R } from '${sub}?real';
import * as React from 'react';
const Panel = React.forwardRef(function Panel(props, ref) { return <R.Panel ref={ref} keepMounted {...props} />; });
export const ${name} = { ...R, Panel };`;

// `radix-ui` / `@base-ui/react` (the all-in-one packages): the real one with Accordion / Collapsible / Tabs replaced by the versions above
const NBC_RADIX_ALL = `export * from 'radix-ui?real';
import * as AccordionNS from '@radix-ui/react-accordion';
import * as CollapsibleNS from '@radix-ui/react-collapsible';
import * as TabsNS from '@radix-ui/react-tabs';
export const Accordion = AccordionNS;
export const Collapsible = CollapsibleNS;
export const Tabs = TabsNS;`;
const NBC_BASE_ALL = `export * from '@base-ui/react?real';
import { Accordion } from '@base-ui/react/accordion';
import { Collapsible } from '@base-ui/react/collapsible';
import { Tabs } from '@base-ui/react/tabs';
export { Accordion, Collapsible, Tabs };`;

export const NBC_WRAP = {
  '@radix-ui/react-accordion': NBC_ACCORDION,
  '@radix-ui/react-collapsible': NBC_COLLAPSIBLE,
  '@radix-ui/react-tabs': NBC_TABS,
  'radix-ui': NBC_RADIX_ALL,
  '@base-ui/react/accordion': baseWrap('@base-ui/react/accordion', 'Accordion'),
  '@base-ui/react/collapsible': baseWrap('@base-ui/react/collapsible', 'Collapsible'),
  '@base-ui/react/tabs': baseWrap('@base-ui/react/tabs', 'Tabs'),
  '@base-ui/react': NBC_BASE_ALL,
};
