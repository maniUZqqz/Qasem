// Easing + spring PRESET LIBRARY: the model never writes a cubic-bezier or spring numbers - it picks a NAME ("ease": "out-expo", "spring": "bouncy").
// Every name here is mirrored by backend/apps/motion/motionlib.py (EASES / SPRINGS) and a test keeps the two lists identical.
import { Easing } from "remotion";

export type EaseFn = (t: number) => number;

const bz = (a: number, b: number, c: number, d: number): EaseFn => Easing.bezier(a, b, c, d);

/** easing curves: t in 0..1 -> 0..1 (back / elastic may overshoot) */
export const EASES: { [name: string]: EaseFn } = {
  "linear": (t) => t,
  "smooth": Easing.inOut(Easing.cubic),
  "out": Easing.out(Easing.cubic),
  "in": Easing.in(Easing.cubic),
  "out-soft": bz(0.22, 1, 0.36, 1),
  "out-expo": bz(0.16, 1, 0.3, 1),
  "in-out-expo": bz(0.87, 0, 0.13, 1),
  "snap": bz(0.5, 0, 0, 1),
  "back": Easing.out(Easing.back(1.7)),
  "in-back": Easing.in(Easing.back(1.4)),
  "elastic": Easing.out(Easing.elastic(1.1)),
  "bounce": Easing.out(Easing.bounce),
};

/** spring configs [damping, stiffness, mass] */
export const SPRINGS: { [name: string]: [number, number, number] } = {
  "gentle": [26, 90, 1],
  "smooth": [30, 120, 1],
  "snappy": [20, 220, 0.8],
  "crisp": [40, 300, 0.7],
  "bouncy": [10, 160, 0.9],
  "elastic": [6, 130, 0.8],
  "heavy": [34, 70, 1.6],
  "slow-reveal": [40, 50, 1.4],
};

export const easeOf = (name?: string | null): EaseFn => (name && EASES[name]) || EASES["out-expo"];
export const springOf = (name?: string | null): [number, number, number] | null => (name && SPRINGS[name]) || null;

/** virtual camera moves of a scene (applied to the parent layer; "parallax" moves the layers at different speeds) */
export const CAMERA_MOVES = ["none", "push-in", "pull-out", "pan-left", "pan-right", "pan-up", "pan-down", "drift", "parallax", "rise"] as const;
export type CameraMove = (typeof CAMERA_MOVES)[number];

/** exits of a scene's content when the scene ends without a transition (cut) */
export const EXIT_KINDS = ["none", "fade", "slide", "zoom", "drop"] as const;
