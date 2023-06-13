import os
from io import BytesIO
from typing import Tuple

from cachetools import FIFOCache
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

from src import logutil

logger = logutil.init_logger(os.path.basename(__file__))

load_dotenv()


def milliseconds_to_string(duration_ms):
    seconds = duration_ms / 1000
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return f"{int(days)} jour(s) {int(hours):02d} heure(s) {int(minutes):02d} minute(s) et {int(seconds):02d} seconde(s)"

def create_dynamic_image(
    text: str,
    font_size: int = 20,
    font_path: str = "src/Menlo-Regular.ttf",
    image_padding: int = 10,
    background_color: str = "#1E1F22",
) -> Tuple[Image.Image, BytesIO]:
    """
    Creates a dynamic image with the specified text.

    Args:
        text (str): The text to display on the image.
        font_size (int): The size of the font to use.
        font_path (str): The path to the font file to use.
        image_padding (int): The amount of padding to add to the image.
        background_color (str): The background color of the image.

    Returns:
        A tuple containing the image object and a BytesIO object containing the image data.
    """
    # Validate input
    if not text:
        raise ValueError("Text cannot be empty")
    if font_size <= 0:
        raise ValueError("Font size must be greater than zero")
    if image_padding < 0:
        raise ValueError("Image padding cannot be negative")

    # Create a font object
    font = ImageFont.truetype(font_path, font_size)

    # Create a drawing object
    draw = ImageDraw.Draw(Image.new("RGB", (0, 0)))

    # Calculate the width and height of the text
    left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font)

    # Add padding to the image size
    image_width = right - left + 2 * image_padding
    image_height = bottom - top + 2 * image_padding

    # Create a new image with the calculated size and background color
    image = Image.new("RGB", (image_width, image_height), color=background_color)

    # Create a new drawing object
    draw = ImageDraw.Draw(image)

    # Calculate the position to center the text
    x = (image_width - (right - left)) // 2
    y = (image_height - (bottom - top)) // 2

    # Draw the text on the image
    draw.multiline_text(
        (x,y), text, font=font, fill=0xF2F3F5
    )

    # Save the image as a PNG file and return the image object and a BytesIO object containing the image data
    imageIO = BytesIO()
    image.save(imageIO, "png")
    imageIO.seek(0)

    return image, imageIO