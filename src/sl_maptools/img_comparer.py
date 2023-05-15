from enum import Enum
from itertools import combinations

import numpy as np
from pathlib import Path
from PIL import Image, ImageFilter
# noinspection PyUnresolvedReferences
from PIL.Image import Resampling, Dither
from skimage.metrics import mean_squared_error as mse
from skimage.metrics import structural_similarity as ssim
from skimage.metrics import normalized_mutual_information as nmi
from skimage.metrics import normalized_root_mse as nrmse

from image_processing import are_similar


mapdir = Path(r"C:\Cache\SL-Carto\Maps2")
# p1 = mapdir / "496-1519_230506-1431.jpg"
# p2 = mapdir / "496-1519_230507-0101.jpg"

# p1 = mapdir / "661-1275_230505-0413.jpg"
# p2 = mapdir / "661-1275_230507-0156.jpg"


# fmt: off
TEST_CASES: list[tuple[bool, list[str]]] = [
    #### Should be similars
    (True, ["400-1549_230506-1422.jpg", "400-1549_230509-0227.jpg"]),
    (True, ["409-1563_230506-0407.jpg", "409-1563_230507-0054.jpg", "409-1563_230509-0225.jpg"]),
    (True, ["408-1552_230506-1422.jpg", "408-1552_230507-0056.jpg"]),

    #### Should be different
    (False, ["406-1578_230506-0402.jpg", "406-1578_230509-0223.jpg"]),
    (False, ["406-1576_230506-0402.jpg", "406-1576_230507-0051.jpg", "406-1576_230509-0223.jpg"]),
    (False, ["402-1572_230506-0404.jpg", "402-1572_230507-0052.jpg", "402-1572_230509-0224.jpg"]),
]
# fmt: on


def compare(im1, im2):
    with (im1.convert("L") as i1, im2.convert("L") as i2):
        i1arr = np.asarray(i1)
        i2arr = np.asarray(i2)
        mse_val = mse(i1arr, i2arr)
        ssim_defa = ssim(i1arr, i2arr)
        ssim_wang = ssim(i1arr, i2arr, gaussian_weights=True, sigma=1.5, use_sample_covariance=False)
        ssim_wangk = ssim(i1arr, i2arr, gaussian_weights=True, sigma=1.5, use_sample_covariance=False, K1=0.02, K2=0.03)
        nmi_val = nmi(i1arr, i2arr)
        nrmse_val = nrmse(i1arr, i2arr)
        print(f"{mse_val=:.3f} {ssim_defa=:.3f} {ssim_wang=:.3f} {ssim_wangk=:.3f} {nmi_val=:.3f} {nrmse_val=:.3f}")


class EnhanceMethod(Enum):
    GB_FE = 0
    GB_FE_B_FE = 1
    GB_GB_FE = 2


def enhance(method: EnhanceMethod, *i: Image.Image) -> tuple[Image.Image, ...]:
    if method == EnhanceMethod.GB_FE:
        return tuple([
            im.filter(ImageFilter.GaussianBlur).filter(ImageFilter.FIND_EDGES)
            for im in i
        ])
    elif method == EnhanceMethod.GB_FE_B_FE:
        return tuple([
            im.filter(ImageFilter.GaussianBlur).filter(ImageFilter.FIND_EDGES).filter(ImageFilter.BLUR).filter(ImageFilter.FIND_EDGES)
            for im in i
        ])
    elif method == EnhanceMethod.GB_GB_FE:
        return tuple([
            im.filter(ImageFilter.GaussianBlur).filter(ImageFilter.GaussianBlur).filter(ImageFilter.FIND_EDGES)
            for im in i
        ])


GREY_PAL = [i for i in range(0, 256, 16)]


def preprocess(im: Image.Image, chg_pal: bool = False) -> Image.Image:
    im_c = im.copy()
    # im_c.thumbnail((64, 64))
    im_p = (
        im_c
        .resize((64, 64), resample=Resampling.BICUBIC)
        .convert("L", dither=Dither.NONE)
        .quantize(colors=16, dither=Dither.NONE)
    )
    if chg_pal:
        # print(im_p.getpalette())
        pal = []
        for i in range(0, 256, 16):
            pal.append(i)
            pal.append(i)
            pal.append(i)
        pal.sort(reverse=True)
        im_p.putpalette(pal)
        # print(im_p.getpalette())
    return im_p.convert("L", dither=Dither.NONE)


def main():
    for i, (expected, flist) in enumerate(TEST_CASES, start=1):
        print("===== Control =====")
        print(f"{expected=} {flist=}")
        for fn in sorted(flist):
            fp = mapdir / fn
            with Image.open(fp) as im:
                print(f"{fp}\n  ", end="")
                compare(im, im)
                print(f"  {are_similar(im, im)=}")

        print("-" * 40)

        for combi in combinations(flist, 2):
            f1, f2 = sorted(combi)
            fp1 = mapdir / f1
            fp2 = mapdir / f2
            with (Image.open(fp1) as im1, Image.open(fp2) as im2):
                print(f"{fp1.name} =?= {fp2.name}  {expected=}")
                rslt = are_similar(im1, im2)
                if rslt.similar != expected:
                    print(f"NOT MATCH, {expected=}")
                else:
                    print("Matched")
                print(f"  {rslt=}")

                print("  Raw:\n    ", end="")
                compare(im1, im2)

                im1c = im1.copy()
                im2c = im2.copy()
                im1c.thumbnail((64, 64))
                im2c.thumbnail((64, 64))
                print("  Raw (thumbnail):\n    ", end="")
                compare(im1c, im2c)

                im1p = preprocess(im1)
                im2p = preprocess(im2)
                print("  Preprocessed:\n    ", end="")
                compare(im1p, im2p)

                im1e, im2e = enhance(EnhanceMethod.GB_FE, im1, im2)
                print("  Enhanced GB_FE:\n    ", end="")
                compare(im1e, im2e)

                im1e, im2e = enhance(EnhanceMethod.GB_FE, im1c, im2c)
                print("  Enhanced GB_FE (thumbnail):\n    ", end="")
                compare(im1e, im2e)

                im1e, im2e = enhance(EnhanceMethod.GB_FE, im1p, im2p)
                print("  Enhanced GB_FE (preprocessed):\n    ", end="")
                compare(im1e, im2e)

                im1e, im2e = enhance(EnhanceMethod.GB_FE_B_FE, im1, im2)
                print("  Enhanced GB_FE_B_FE:\n    ", end="")
                compare(im1e, im2e)

                im1e, im2e = enhance(EnhanceMethod.GB_GB_FE, im1, im2)
                print("  Enhanced GB_GB_FE:\n    ", end="")
                compare(im1e, im2e)

                im1e.close()
                im2e.close()
                im1e = None
                im2e = None

        print()


if __name__ == '__main__':
    main()
