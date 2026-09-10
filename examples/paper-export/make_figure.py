"""Generate a wholly synthetic chart locally; no downloaded assets or real data."""
from pathlib import Path
from PIL import Image, ImageDraw


def main():
    path = Path(__file__).with_name("toy-figure.png")
    image = Image.new("RGB", (1300, 640), "white")
    draw = ImageDraw.Draw(image)
    left, bottom, right, top = 120, 550, 1190, 60
    draw.line((left, top, left, bottom, right, bottom), fill="black", width=4)
    points = []
    for i in range(5):
        x, y = left + (right-left)*i/4, bottom - (bottom-top)*(1+2*i)/10
        points.append((x, y))
        draw.text((x-5, bottom+16), str(i), fill="black", font_size=25)
    for y in range(0, 11, 2):
        py = bottom - (bottom-top)*y/10
        draw.text((left-45, py-12), str(y), fill="black", font_size=25)
    draw.line(points, fill="#2166ac", width=5)
    for x, y in points:
        draw.ellipse((x-9,y-9,x+9,y+9), fill="#b2182b")
    draw.text((610, 602), "x (m)", fill="black", font_size=28)
    draw.text((12, 12), "y (dimensionless)", fill="black", font_size=26)
    draw.text((800, 80), "Synthetic: y = 1 + 2x", fill="black", font_size=26)
    image.save(path)
    print(path)


if __name__ == "__main__":
    main()
