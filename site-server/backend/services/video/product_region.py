"""Where the shop's product is in a frame — from the shop's own product photo.

Offline and CPU-only: ORB features of the product photo are matched against
the frame (Lowe's ratio test), and a RANSAC homography keeps only the matches
that agree on one placement of one flat-ish object. The number of agreeing
matches (inliers) says how surely the product is there; the homography maps
the photo's outline into the frame, which is the product's region.

Three users:

* **Narration timing** (services.audio.timing) — when the product first
  appears.
* **Product exposure** (services.video.qc) — whether the PRODUCT is lit well,
  not the frame: a gold watch on black velvet is a dark frame and a perfect
  product shot; a dark bag on a white sweep is a bright frame and a bad one.
* **Product consistency without a GPU** (services.video.qc) — whether the
  product stays the same product through the clip when the vision model is
  not available to say so.

Honest limit: ORB needs texture. A plain matte product with no print, seams
or logo gives few features, `locate` returns nothing, and every caller then
says "could not check" instead of guessing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: A frame counts as "product found" at this many RANSAC inliers or more.
MIN_INLIERS = 12
#: The photo is matched at this size (longest side); larger costs time and
#: finds the same product.
PHOTO_SIZE = 640


@dataclass
class Found:
    """The product in one frame."""

    inliers: int = 0
    #: Outline as four (x, y) points in FRACTIONS of the frame, or empty.
    polygon: list = field(default_factory=list)
    #: Photo → frame (pixels of the frame that was searched), or None.
    homography: object = None

    @property
    def seen(self) -> bool:
        return self.inliers >= MIN_INLIERS and len(self.polygon) == 4


class Matcher:
    """The product photo, prepared once, matched against many frames."""

    def __init__(self, product_image):
        import cv2

        photo = cv2.imread(str(product_image), cv2.IMREAD_GRAYSCALE)
        if photo is None:
            raise ValueError("عکس محصول خوانده نشد")
        scale = PHOTO_SIZE / max(photo.shape)
        if scale < 1:
            photo = cv2.resize(photo, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        self.photo_shape = photo.shape[:2]
        colour = cv2.imread(str(product_image), cv2.IMREAD_COLOR)
        if scale < 1:
            colour = cv2.resize(colour, (photo.shape[1], photo.shape[0]), interpolation=cv2.INTER_AREA)
        self.photo_lab = cv2.cvtColor(colour, cv2.COLOR_BGR2LAB)
        self.photo_gray = photo
        # The product's own brightness in the shop's photo — the reference a
        # rendered frame is judged against. A black bag is dark in its photo
        # too; only a product much darker in the video than in its photo is
        # underexposed. Near-white and near-black pixels are left out: they
        # are the backdrop of a catalogue shot, not the product.
        import numpy as np

        body = photo[(photo > 12) & (photo < 243)]
        self.photo_p50 = float(np.percentile(body, 50)) if body.size > 500 else None
        self.orb = cv2.ORB_create(nfeatures=1200, scaleFactor=1.2, nlevels=8)
        self.keys, self.desc = self.orb.detectAndCompute(photo, None)
        if self.desc is None or len(self.keys) < 20:
            raise ValueError("عکس محصول جزئیات کافی برای پیدا کردنش در ویدیو ندارد")
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def find(self, gray) -> Found:
        """The product in one greyscale frame (numpy uint8 array)."""
        import cv2
        import numpy as np

        keys, desc = self.orb.detectAndCompute(gray, None)
        if desc is None or len(keys) < 8:
            return Found()
        good = []
        for pair in self.matcher.knnMatch(self.desc, desc, k=2):
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
                good.append(pair[0])
        if len(good) < 8:
            return Found()
        src = np.float32([self.keys[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([keys[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if homography is None or mask is None:
            return Found()
        inliers = int(mask.sum())
        h, w = self.photo_shape
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        outline = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
        fh, fw = gray.shape[:2]
        polygon = [(float(x) / fw, float(y) / fh) for x, y in outline]
        if not _plausible(polygon):
            # A homography that folds the photo into a bow-tie or a sliver is
            # a coincidence of matches, not the product.
            return Found(inliers=inliers)
        return Found(inliers=inliers, polygon=polygon, homography=homography)


def _plausible(polygon) -> bool:
    """Convex, not tiny, not absurdly larger than the frame."""
    import numpy as np

    points = np.asarray(polygon, dtype=np.float64)
    area = 0.5 * abs(np.dot(points[:, 0], np.roll(points[:, 1], 1)) - np.dot(points[:, 1], np.roll(points[:, 0], 1)))
    if not (0.002 <= area <= 4.0):
        return False
    signs = []
    for i in range(4):
        a, b, c = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
        signs.append(np.sign((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])))
    return len(set(signs)) == 1


def mask_for(polygon, shape):
    """Boolean mask of the product region in a frame of `shape` (h, w)."""
    import cv2
    import numpy as np

    h, w = shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    points = np.int32([[x * w, y * h] for x, y in polygon])
    cv2.fillConvexPoly(mask, points, 1)
    return mask.astype(bool)


def colour_distance(matcher: Matcher, frame_bgr, found: Found) -> float | None:
    """How far the product's colour in the frame is from its photo (ΔE-ish).

    The frame is warped back onto the photo's own coordinates, so the SAME
    parts of the product are compared, and only the chroma (a*, b* in Lab) —
    lighting changes brightness, a morphing model changes the colour. The
    photo's backdrop (near-white / near-black) and the warp's empty border
    are left out. Median over pixels, so a hand passing in front of one
    corner does not count as a different product.
    """
    import cv2
    import numpy as np

    if found.homography is None:
        return None
    h, w = matcher.photo_shape
    try:
        inverse = np.linalg.inv(found.homography)
    except np.linalg.LinAlgError:
        return None
    back = cv2.warpPerspective(frame_bgr, inverse, (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    covered = cv2.warpPerspective(np.full(frame_bgr.shape[:2], 255, np.uint8), inverse, (w, h)) > 0
    body = (matcher.photo_gray > 12) & (matcher.photo_gray < 243) & covered
    if body.sum() < 400:
        return None
    lab = cv2.cvtColor(back, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = matcher.photo_lab.astype(np.float32)
    delta = np.sqrt(((lab[..., 1:] - ref[..., 1:]) ** 2).sum(axis=-1))[body]
    return float(np.median(delta))


def aspect(found: Found) -> float | None:
    """Width / height of the found outline (mean of opposite sides)."""
    import math

    if len(found.polygon) != 4:
        return None
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = found.polygon
    top = math.dist((x0, y0), (x1, y1))
    bottom = math.dist((x3, y3), (x2, y2))
    left = math.dist((x0, y0), (x3, y3))
    right = math.dist((x1, y1), (x2, y2))
    height = (left + right) / 2
    return (top + bottom) / 2 / height if height else None
