import os
import asyncio
import aiohttp
from datetime import datetime
from config import SD_API_URL, STYLES
from aiogram import Bot
import imageio
import subprocess
import base64
from io import BytesIO
from typing import Optional, Callable, Awaitable

from moviepy.editor import ImageSequenceClip, AudioFileClip

# Оптимизированные параметры
FRAME_COUNT = 8  # Было 12 → стало 8 (меньше кадров = быстрее)
IMAGE_WIDTH = 256  # Было 512 → стало 384 (меньше разрешение = быстрее)
IMAGE_HEIGHT = 256
SD_STEPS = 10  # Было 20 → стало 15 (меньше шагов = быстрее)
SD_DENOISING_STRENGTH = 0.5  # Было 0.5-0.6 → теперь фиксированное 0.5


async def generate_sd_frame(session: aiohttp.ClientSession, input_path: str, style: str, frame_num: int):
    try:
        with open(input_path, "rb") as image_file:
            img_base64 = base64.b64encode(image_file.read()).decode('utf-8')

        # Проверяем, что стиль существует в конфиге
        if style not in STYLES:
            raise Exception(f"Стиль '{style}' не найден в конфигурации")

        params = {
            "init_images": [img_base64],
            "prompt": f"{STYLES[style]}, frame {frame_num}",
            "negative_prompt": "blurry, lowres, bad anatomy, ugly, text, watermark",
            "steps": SD_STEPS,
            "denoising_strength": SD_DENOISING_STRENGTH,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "cfg_scale": 7,  # Добавляем параметр для контроля креативности
        }

        async with session.post(
                f"{SD_API_URL}/sdapi/v1/img2img",
                json=params,
                headers={"Content-Type": "application/json"},
                timeout=300  # Увеличиваем таймаут для обработки
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                raise Exception(f"API Error {resp.status}: {error}")

            response = await resp.json()
            if 'images' not in response or not response['images']:
                raise Exception("Нет изображений в ответе от SD API")

            return response['images'][0]

    except aiohttp.ClientError as e:
        raise Exception(f"Сетевая ошибка при генерации кадра: {str(e)}")
    except Exception as e:
        raise Exception(f"Ошибка генерации кадра {frame_num}: {str(e)}")


async def generate_frames(photo_file: str, style: str, bot: Bot,
                          progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None):
    """Генерация кадров с улучшенной обработкой ошибок"""
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    input_path = os.path.join(temp_dir, f"input_{photo_file}.jpg")

    try:
        # Скачиваем фото
        try:
            file = await bot.get_file(photo_file)
            file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Ошибка загрузки фото: {resp.status}")
                    with open(input_path, 'wb') as f:
                        f.write(await resp.read())
        except Exception as e:
            raise Exception(f"Ошибка загрузки фото: {str(e)}")

        # Генерация кадров
        frames = []
        async with aiohttp.ClientSession() as session:
            for i in range(FRAME_COUNT):
                try:
                    if progress_callback:
                        await progress_callback(i, FRAME_COUNT)

                    frame = await generate_sd_frame(session, input_path, style, i)
                    frames.append(frame)
                except Exception as e:
                    print(f"⚠️ Пропущен кадр {i} из-за ошибки: {e}")
                    continue

        if len(frames) < FRAME_COUNT // 2:  # Если сгенерировано меньше половины кадров
            raise Exception(f"Сгенерировано только {len(frames)}/{FRAME_COUNT} кадров")

        return frames

    finally:
        if os.path.exists(input_path):
            try:
                os.remove(input_path)
            except:
                pass


async def create_video(frames: list, output_path: str, fps: int = 8):
    try:
        # Сохраняем кадры как изображения
        temp_images = []
        for i, frame_data in enumerate(frames):
            img_data = base64.b64decode(frame_data)
            img_path = f"temp_frame_{i}.png"
            with open(img_path, 'wb') as f:
                f.write(img_data)
            temp_images.append(img_path)

        # Создаем видео
        clip = ImageSequenceClip(temp_images, fps=fps)
        clip.write_videofile(output_path, codec="libx264", audio=False)

        # Удаляем временные файлы
        for img_path in temp_images:
            os.remove(img_path)
    except Exception as e:
        raise Exception(f"Ошибка при создании видео: {str(e)}")

async def generate_ai_video(photo_files: list, style: str, bot: Bot,
                            progress_callback: Optional[Callable[[int], Awaitable[None]]] = None) -> str:
    """Финальная функция с прогрессом"""
    try:
        total_steps = FRAME_COUNT + 1  # +1 для этапа создания видео
        current_step = 0

        def update_progress():
            nonlocal current_step
            current_step += 1
            if progress_callback:
                progress = int((current_step / total_steps) * 100)
                asyncio.create_task(progress_callback(progress))

        # Генерация кадров
        frames = []
        temp_dir = "temp"
        os.makedirs(temp_dir, exist_ok=True)
        input_path = os.path.join(temp_dir, f"input_{photo_files[0]}.jpg")

        # Скачиваем фото
        try:
            file = await bot.get_file(photo_files[0])
            file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    with open(input_path, 'wb') as f:
                        f.write(await resp.read())
        except Exception as e:
            raise Exception(f"Ошибка загрузки фото: {str(e)}")

        # Генерация кадров
        async with aiohttp.ClientSession() as session:
            for i in range(FRAME_COUNT):
                try:
                    frame = await generate_sd_frame(session, input_path, style, i)
                    frames.append(frame)
                    update_progress()
                except Exception as e:
                    print(f"⚠️ Пропущен кадр {i} из-за ошибки: {e}")
                    continue

        if not frames:
            raise Exception("Не удалось сгенерировать ни одного кадра")

        # Создание видео
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        video_path = os.path.join(output_dir, f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        await create_video(frames, video_path)
        update_progress()

        return video_path

    except Exception as e:
        raise Exception(f"❌ Ошибка: {str(e)}")
    finally:
        # Очистка временных файлов
        if os.path.exists(input_path):
            os.remove(input_path)