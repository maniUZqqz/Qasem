// Safe stand-ins for the libraries React/Tailwind components usually import. Each entry is TSX source bundled in place of the real package:
// no network, no browser APIs, static output. Animations are dropped (the converted component is a still); layout and classes are kept.

const CN = `import { clsx } from 'clsx'; import { twMerge } from 'tailwind-merge';
export function cn(...inputs) { return twMerge(clsx(inputs)); }
export default cn;`;

const HOOKS = `export function useIsMobile() { return false; }
export const useMobile = useIsMobile;
export function useMediaQuery(_q) { return false; }
export default useIsMobile;`;

const MOTION = `import * as React from 'react';
const STRIP = new Set(['initial','animate','exit','whileHover','whileTap','whileInView','whileFocus','whileDrag','variants','transition','viewport','layout','layoutId','drag',
  'dragConstraints','dragElastic','dragMomentum','onAnimationComplete','onAnimationStart','onViewportEnter','onViewportLeave','custom','inherit','transformTemplate','onUpdate',
  'onHoverStart','onHoverEnd','onTap','onTapStart','onTapCancel','onPan','onDrag','onDragStart','onDragEnd','layoutDependency','layoutScroll','dragSnapToOrigin']);
function plain(style) {
  if (!style || typeof style !== 'object') return style;
  const out = {};
  for (const [k, v] of Object.entries(style)) {
    const val = v && typeof v.get === 'function' ? v.get() : v;
    if (typeof val === 'number' || typeof val === 'string') out[k] = val;
  }
  return out;
}
const cache = {};
function make(tag) {
  return React.forwardRef(function Motion(props, ref) {
    const rest = {};
    for (const k of Object.keys(props)) if (!STRIP.has(k)) rest[k] = props[k];
    rest.style = plain(props.style);
    return React.createElement(tag, { ...rest, ref });
  });
}
function wrapC(C) {
  return React.forwardRef(function MotionWrapped(props, ref) {
    const rest = {};
    for (const k of Object.keys(props)) if (!STRIP.has(k)) rest[k] = props[k];
    rest.style = plain(props.style);
    return React.createElement(C, { ...rest, ref });
  });
}
export const motion = new Proxy(function () {}, {
  get(_t, tag) { if (tag === 'create') return wrapC; return cache[tag] || (cache[tag] = make(tag)); },
  apply(_t, _this, args) { return wrapC(args[0]); },
});
export const m = motion;
const Pass = ({ children }) => React.createElement(React.Fragment, null, children);
export const AnimatePresence = Pass; export const LazyMotion = Pass; export const MotionConfig = Pass;
export const domAnimation = {}; export const domMax = {};
export const createMotionComponent = (C) => C;
const mv = (v = 0) => ({ get: () => v, set() {}, on: () => () => {}, onChange: () => () => {}, getVelocity: () => 0, isAnimating: () => false, stop() {}, jump() {} });
export const useMotionValue = (v) => mv(v);
export const useSpring = (v) => mv(typeof v === 'number' ? v : 0);
export const useTransform = (_v, _i, o) => mv(Array.isArray(o) ? o[0] : 0);
export const useScroll = () => ({ scrollX: mv(0), scrollY: mv(0), scrollXProgress: mv(0), scrollYProgress: mv(0) });
export const useVelocity = () => mv(0);
export const useMotionTemplate = (s, ...vals) => mv(s.map((x, i) => x + (vals[i] && vals[i].get ? vals[i].get() : (vals[i] ?? ''))).join(''));
export const useMotionValueEvent = () => {};
export const useAnimationFrame = () => {};
export const useMotionValueState = (v) => (v && v.get ? v.get() : 0);
export const useWillChange = () => mv(0);
export const useInView = () => true;
export const useReducedMotion = () => true;
export const useAnimation = () => ({ start: async () => {}, stop() {}, set() {} });
export const useAnimationControls = useAnimation;
export const useAnimate = () => [{ current: null }, () => ({ stop() {} })];
export const useCycle = (...a) => [a[0], () => {}];
export const useIsPresent = () => true;
export const usePresence = () => [true, () => {}];
export const animate = () => ({ stop() {}, then: (f) => f && f() });
export const stagger = () => 0;
export const Reorder = { Group: Pass, Item: Pass };
export const LayoutGroup = Pass; export const AnimateSharedLayout = Pass; export const MotionConfigContext = React.createContext({});
export const useDragControls = () => ({ start() {} });
export const useTime = () => mv(0);
export const useElementScroll = () => ({ scrollX: mv(0), scrollY: mv(0), scrollXProgress: mv(0), scrollYProgress: mv(0) });
export const transform = (v, i, o) => (Array.isArray(o) ? o[0] : v);
export const interpolate = () => (v) => v;
export const cubicBezier = () => (t) => t;
export const easeIn = (t) => t, easeOut = (t) => t, easeInOut = (t) => t, linear = (t) => t, circOut = (t) => t, backOut = (t) => t, anticipate = (t) => t;
export const MotionValue = function MotionValue(v) { return mv(v); };
export const motionValue = (v) => mv(v);
export const spring = () => ({});
export const clamp = (a, b, v) => Math.min(b, Math.max(a, v));
export const wrap = (a, b, v) => v;
export const mix = (a, b, t) => a + (b - a) * t;
export const progress = (a, b, v) => (v - a) / (b - a || 1);
export default motion;`;

export const SHIM_SOURCES = {
  'lib/utils': CN, 'lib/cn': CN, 'utils/cn': CN, 'lib/classnames': CN, 'utils': CN, 'cn': CN,
  'hooks/use-mobile': HOOKS, 'hooks/use-media-query': HOOKS,
  'next/image': `import * as React from 'react';
export default function Image(props) {
  const { src, alt = '', width, height, fill, className, style, priority, quality, placeholder, blurDataURL, sizes, loader, unoptimized, ...rest } = props;
  const s = fill ? { position: 'absolute', inset: 0, width: '100%', height: '100%', ...(style || {}) } : style;
  const url = typeof src === 'string' ? src : (src && src.src) || '';
  return React.createElement('img', { src: url, alt, width: fill ? undefined : width, height: fill ? undefined : height, className, style: s, ...rest });
}`,
  'next/link': `import * as React from 'react';
export default function Link({ href, children, prefetch, replace, scroll, shallow, passHref, legacyBehavior, ...rest }) {
  return React.createElement('a', { href: typeof href === 'string' ? href : (href && href.pathname) || '#', ...rest }, children);
}`,
  'next/navigation': `export const usePathname = () => '/'; export const useRouter = () => ({ push() {}, replace() {}, back() {}, prefetch() {} });
export const useSearchParams = () => new URLSearchParams(); export const useParams = () => ({});`,
  'next/dynamic': `export default function dynamic() { return function Dynamic() { return null; }; }`,
  'next/head': `export default function Head() { return null; }`,
  'next/font/google': `const f = () => ({ className: '', style: {}, variable: '' });
export const Inter = f, Poppins = f, Roboto = f, Geist = f, Geist_Mono = f, Outfit = f, DM_Sans = f, Playfair_Display = f, Space_Grotesk = f, Manrope = f, Lora = f, Montserrat = f;
export default f;`,
  'next/font/local': `export default function local() { return { className: '', style: {}, variable: '' }; }`,
  'next-themes': `import * as React from 'react';
export const useTheme = () => ({ theme: 'light', resolvedTheme: 'light', setTheme() {}, themes: ['light', 'dark'] });
export function ThemeProvider({ children }) { return React.createElement(React.Fragment, null, children); }`,
  'framer-motion': MOTION, 'motion/react': MOTION, 'motion': MOTION, 'motion/react-client': MOTION,
  'react-intersection-observer': `import * as React from 'react';
export function useInView() { const r = [() => {}, true, undefined]; r.ref = r[0]; r.inView = true; r.entry = undefined; return r; }
export const InView = ({ children }) => React.createElement(React.Fragment, null, typeof children === 'function' ? children({ inView: true, ref: () => {} }) : children);`,
  'react-use-measure': `export default function useMeasure() { return [() => {}, { width: 600, height: 400, top: 0, left: 0, bottom: 400, right: 600, x: 0, y: 0 }]; }`,
  'usehooks-ts': `export const useMediaQuery = () => false; export const useIsClient = () => true; export const useWindowSize = () => ({ width: 1280, height: 800 });
export const useLocalStorage = (_k, v) => [v, () => {}]; export const useOnClickOutside = () => {};`,
  '@uidotdev/usehooks': `export const useMediaQuery = () => false; export const useWindowSize = () => ({ width: 1280, height: 800 });`,
};
SHIM_SOURCES['react-icons'] = `import * as React from 'react';
const I = (p) => React.createElement('svg', { viewBox: '0 0 24 24', width: '1em', height: '1em', fill: 'currentColor', 'aria-hidden': true, ...p }, React.createElement('circle', { cx: 12, cy: 12, r: 5 }));
export default I;`;

// shadcn/ui primitives (MIT, https://ui.shadcn.com): the same API with plain Tailwind classes, built on the Radix packages installed next to this file.
export const UI_SOURCES = {
  button: `import * as React from 'react'; import { Slot } from '@radix-ui/react-slot'; import { cva } from 'class-variance-authority'; import { cn } from '@/lib/utils';
const buttonVariants = cva('inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0', {
  variants: { variant: { default: 'bg-primary text-primary-foreground hover:bg-primary/90', destructive: 'bg-destructive text-white hover:bg-destructive/90', outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground', secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80', ghost: 'hover:bg-accent hover:text-accent-foreground', link: 'text-primary underline-offset-4 hover:underline' },
    size: { default: 'h-9 px-4 py-2', sm: 'h-8 rounded-md px-3 text-xs', lg: 'h-10 rounded-md px-8', icon: 'size-9' } }, defaultVariants: { variant: 'default', size: 'default' } });
const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => { const Comp = asChild ? Slot : 'button'; return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />; });
Button.displayName = 'Button';
export { Button, buttonVariants }; export default Button;`,
  card: `import * as React from 'react'; import { cn } from '@/lib/utils';
const mk = (cls) => React.forwardRef(({ className, ...p }, ref) => <div ref={ref} className={cn(cls, className)} {...p} />);
export const Card = mk('rounded-xl border bg-card text-card-foreground shadow'); export const CardHeader = mk('flex flex-col space-y-1.5 p-6'); export const CardTitle = mk('font-semibold leading-none tracking-tight');
export const CardDescription = mk('text-sm text-muted-foreground'); export const CardContent = mk('p-6 pt-0'); export const CardFooter = mk('flex items-center p-6 pt-0'); export const CardAction = mk('self-start');`,
  badge: `import * as React from 'react'; import { cva } from 'class-variance-authority'; import { cn } from '@/lib/utils';
export const badgeVariants = cva('inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors', { variants: { variant: { default: 'border-transparent bg-primary text-primary-foreground', secondary: 'border-transparent bg-secondary text-secondary-foreground', destructive: 'border-transparent bg-destructive text-white', outline: 'text-foreground' } }, defaultVariants: { variant: 'default' } });
export function Badge({ className, variant, ...props }) { return <div className={cn(badgeVariants({ variant }), className)} {...props} />; }
export default Badge;`,
  input: `import * as React from 'react'; import { cn } from '@/lib/utils';
export const Input = React.forwardRef(({ className, type, ...props }, ref) => <input type={type} className={cn('flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm placeholder:text-muted-foreground', className)} ref={ref} {...props} />);
export default Input;`,
  textarea: `import * as React from 'react'; import { cn } from '@/lib/utils';
export const Textarea = React.forwardRef(({ className, ...props }, ref) => <textarea className={cn('flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground', className)} ref={ref} {...props} />);
export default Textarea;`,
  label: `import * as React from 'react'; import * as L from '@radix-ui/react-label'; import { cn } from '@/lib/utils';
export const Label = React.forwardRef(({ className, ...props }, ref) => <L.Root ref={ref} className={cn('text-sm font-medium leading-none', className)} {...props} />);
export default Label;`,
  separator: `import * as React from 'react'; import * as S from '@radix-ui/react-separator'; import { cn } from '@/lib/utils';
export const Separator = React.forwardRef(({ className, orientation = 'horizontal', decorative = true, ...props }, ref) => <S.Root ref={ref} decorative={decorative} orientation={orientation} className={cn('shrink-0 bg-border', orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px', className)} {...props} />);
export default Separator;`,
  avatar: `import * as React from 'react'; import * as A from '@radix-ui/react-avatar'; import { cn } from '@/lib/utils';
export const Avatar = React.forwardRef(({ className, ...p }, ref) => <A.Root ref={ref} className={cn('relative flex size-10 shrink-0 overflow-hidden rounded-full', className)} {...p} />);
export const AvatarImage = React.forwardRef(({ className, ...p }, ref) => <A.Image ref={ref} className={cn('aspect-square size-full', className)} {...p} />);
export const AvatarFallback = React.forwardRef(({ className, ...p }, ref) => <A.Fallback ref={ref} className={cn('flex size-full items-center justify-center rounded-full bg-muted', className)} {...p} />);`,
  accordion: `import * as React from 'react'; import * as A from '@radix-ui/react-accordion'; import { ChevronDown } from 'lucide-react'; import { cn } from '@/lib/utils';
export const Accordion = A.Root; export const AccordionItem = React.forwardRef(({ className, ...p }, ref) => <A.Item ref={ref} className={cn('border-b', className)} {...p} />);
export const AccordionTrigger = React.forwardRef(({ className, children, ...p }, ref) => <A.Header className="flex"><A.Trigger ref={ref} className={cn('flex flex-1 items-center justify-between py-4 text-sm font-medium transition-all hover:underline [&[data-state=open]>svg]:rotate-180', className)} {...p}>{children}<ChevronDown className="h-4 w-4 shrink-0 transition-transform duration-200" /></A.Trigger></A.Header>);
export const AccordionContent = React.forwardRef(({ className, children, ...p }, ref) => <A.Content ref={ref} className="overflow-hidden text-sm" {...p}><div className={cn('pb-4 pt-0', className)}>{children}</div></A.Content>);`,
  tabs: `import * as React from 'react'; import * as T from '@radix-ui/react-tabs'; import { cn } from '@/lib/utils';
export const Tabs = T.Root; export const TabsList = React.forwardRef(({ className, ...p }, ref) => <T.List ref={ref} className={cn('inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground', className)} {...p} />);
export const TabsTrigger = React.forwardRef(({ className, ...p }, ref) => <T.Trigger ref={ref} className={cn('inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow', className)} {...p} />);
export const TabsContent = React.forwardRef(({ className, ...p }, ref) => <T.Content ref={ref} className={cn('mt-2', className)} {...p} />);`,
  switch: `import * as React from 'react'; import * as S from '@radix-ui/react-switch'; import { cn } from '@/lib/utils';
export const Switch = React.forwardRef(({ className, ...p }, ref) => <S.Root className={cn('peer inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent bg-input data-[state=checked]:bg-primary', className)} {...p} ref={ref}><S.Thumb className="pointer-events-none block size-4 rounded-full bg-background shadow-lg data-[state=checked]:translate-x-4" /></S.Root>);`,
  checkbox: `import * as React from 'react'; import * as C from '@radix-ui/react-checkbox'; import { Check } from 'lucide-react'; import { cn } from '@/lib/utils';
export const Checkbox = React.forwardRef(({ className, ...p }, ref) => <C.Root ref={ref} className={cn('peer size-4 shrink-0 rounded-sm border border-primary shadow data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground', className)} {...p}><C.Indicator className="flex items-center justify-center text-current"><Check className="size-3.5" /></C.Indicator></C.Root>);`,
  progress: `import * as React from 'react'; import * as P from '@radix-ui/react-progress'; import { cn } from '@/lib/utils';
export const Progress = React.forwardRef(({ className, value, ...p }, ref) => <P.Root ref={ref} className={cn('relative h-2 w-full overflow-hidden rounded-full bg-primary/20', className)} {...p}><P.Indicator className="h-full w-full flex-1 bg-primary" style={{ transform: 'translateX(-' + (100 - (value || 0)) + '%)' }} /></P.Root>);`,
  collapsible: `import * as C from '@radix-ui/react-collapsible'; export const Collapsible = C.Root; export const CollapsibleTrigger = C.Trigger; export const CollapsibleContent = C.Content;`,
  skeleton: `import * as React from 'react'; import { cn } from '@/lib/utils'; export function Skeleton({ className, ...p }) { return <div className={cn('animate-pulse rounded-md bg-primary/10', className)} {...p} />; }`,
};
