import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.enums import ContentType
from aiogram.types import user
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiohttp
import os
from time import time

from models import Base, User, Upload, VideoTask, ProcessingStyle, TaskStatus, TaskImage
from session import engine, async_session
from config import SD_API_URL, STYLES

from sqlalchemy import select, delete, insert, update
from sqlalchemy.exc import NoResultFound, IntegrityError

from ai_processing import generate_ai_video

from config import BOT_TOKEN

from aiogram.types import InputFile

# Инициализация
dp = Dispatcher()
bot = Bot(token=BOT_TOKEN)
scheduler = AsyncIOScheduler()

# Кэш для временных данных
user_temp_data = {}
progress_tracker = {}


@dp.message(Command("help"))
async def help_command(message: types.Message):
    help_text = (
        "📚 Как пользоваться ботом:\n\n"
        "1. Отправьте ОДНО фото\n"
        "2. Нажмите кнопку '🎨 Выбрать стиль и создать видео'\n"
        "3. Выберите стиль из предложенных\n"
        "4. Подождите около часа пока идет обработка\n"
        "5. Получите готовое видео!\n\n"
        "Обратите внимание: одновременно можно обрабатывать только одно фото."
    )
    await message.answer(help_text)


@dp.message(Command("info"))
async def info_command(message: types.Message):
    info_text = (
        "ℹ️ Информация о боте:\n\n"
        "Этот бот превращает ваши фото в видео в разных стилях "
        "с помощью искусственного интеллекта.\n\n"
        "Технологии: Stable Diffusion, Python, AIogram\n"
        "Обработка одного видео занимает около 5 минут."
    )
    await message.answer(info_text)


@dp.message(Command("secure"))
async def secure_command(message: types.Message):
    secure_text = (
        "🔒 Безопасность данных:\n\n"
        "Все фото и видео хранятся на серверах Telegram, "
        "и никто, включая владельца бота, не может их увидеть.\n\n"
        "Мы не сохраняем ваши медиафайлы на своих серверах(у нас их нет:()."
    )
    await message.answer(secure_text)


@dp.message(Command("owner"))
async def owner_command(message: types.Message):
    await message.answer("Мой создатель: @artemtya")


async def get_file_url(file_id: str) -> str:
    """Получение URL файла в Telegram"""
    file = await bot.get_file(file_id)
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"


async def download_file(url: str, path: str):
    """Скачивание файла по URL"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            with open(path, 'wb') as f:
                f.write(await resp.read())


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        'Привет! Отправь мне фото, и я превращу его в видео в выбранном стиле! 📷🎥\n\n'
        'За конфиденциальность не переживайте, никто не может видеть ваших фотографий!'
    )


@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, есть ли уже фото у пользователя
    if user_id in user_temp_data and user_temp_data[user_id].get("uploads"):
        await message.answer("❌ Вы уже отправили фото. Дождитесь завершения текущей обработки.")
        return

    file_id = message.photo[-1].file_id

    async with async_session() as session:
        try:
            # Регистрация/обновление пользователя
            user = await session.execute(select(User).where(User.telegram_id == user_id))
            user = user.scalar()

            if not user:
                user = User(
                    telegram_id=user_id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name,
                )
                session.add(user)
                await session.commit()

            # Сохраняем загрузку (только одну)
            await session.execute(delete(Upload).where(Upload.user_id == user.id))
            upload = Upload(
                user_id=user.id,
                file_id=file_id,
                is_photo="1"
            )
            session.add(upload)
            await session.commit()

            # Сохраняем во временные данные
            user_temp_data[user_id] = {"uploads": [file_id]}

            # Инициализируем трекер прогресса
            progress_tracker[user_id] = {
                "start_time": None,
                "progress": 0,
                "message_id": None
            }

            # Клавиатура с действиями
            builder = ReplyKeyboardBuilder()
            builder.button(text="🎨 Выбрать стиль и создать видео")
            await message.answer(
                "Фото сохранено! Теперь выберите стиль для видео. "
                "Обработка займет около часа.",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )

        except Exception as e:
            await message.answer(f"Ошибка: {str(e)}")


@dp.message(F.text == "🎨 Выбрать стиль и создать видео")
async def select_style(message: types.Message):
    user_id = message.from_user.id

    if user_id not in user_temp_data or not user_temp_data[user_id].get("uploads"):
        await message.answer("Сначала загрузите фото!")
        return

    async with async_session() as session:
        try:
            styles = await session.execute(select(ProcessingStyle))
            styles = styles.scalars().all()

            if not styles:
                await message.answer("⚠️ Нет доступных стилей. Попробуйте позже.")
                return

            builder = InlineKeyboardBuilder()
            for style in styles:
                builder.button(
                    text=style.style_name,
                    callback_data=f"style_{style.id}"
                )
            builder.adjust(2)

            await message.answer(
                "Выберите стиль обработки:",
                reply_markup=builder.as_markup()
            )

        except Exception as e:
            await message.answer(f"Ошибка при загрузке стилей: {str(e)}")


@dp.callback_query(F.data.startswith("style_"))
async def process_style_selection(callback: types.CallbackQuery):
    """Обработчик выбора стиля для создания видео"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    try:
        # 1. Извлекаем ID стиля
        try:
            style_id = int(callback.data.split("_")[1])
        except (IndexError, ValueError):
            await callback.answer("Неверный формат стиля!")
            return

        # 2. Проверяем наличие загруженного фото
        if not user_temp_data.get(user_id, {}).get("uploads"):
            await callback.answer("Сначала загрузите фото!")
            return

        async with async_session() as session:
            try:
                # 3. Получаем данные стиля
                style = await session.get(ProcessingStyle, style_id)
                if not style:
                    await callback.answer("Стиль недоступен!")
                    return

                # 4. Получаем пользователя
                user = await session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                user = user.scalar_one_or_none()

                if not user:
                    await callback.answer("Пользователь не найден!")
                    return

                # 5. Создаем задачу обработки
                task = VideoTask(
                    user_id=user.id,
                    status_id=1,  # pending
                    style_id=style.id,
                    created_at=datetime.now()
                )
                session.add(task)
                await session.flush()

                # 6. Связываем фото с задачей
                upload = await session.execute(
                    select(Upload)
                    .where(Upload.file_id == user_temp_data[user_id]["uploads"][0])
                    .limit(1)
                )
                upload = upload.scalar_one_or_none()

                if upload:
                    task_image = TaskImage(
                        task_id=task.id,
                        upload_id=upload.id,
                        order_index=0
                    )
                    session.add(task_image)

                await session.commit()

                # 7. Инициализируем прогресс
                progress_msg = await bot.send_message(
                    chat_id=chat_id,
                    text="🔄 Начинаю обработку..."
                )
                progress_tracker[user_id] = {
                    "start_time": time(),
                    "progress": 0,
                    "message_id": progress_msg.message_id,
                    "task_id": task.id,
                    "chat_id": chat_id
                }

                await callback.answer(f"Стиль: {style.style_name}")

                # 8. Обновляем статус задачи
                task.status_id = 2  # processing
                await session.commit()

                # 9. Генерируем видео
                try:
                    video_path = await generate_ai_video(
                        user_temp_data[user_id]["uploads"],
                        style.style_name.lower(),
                        bot,
                        progress_callback=lambda p: update_progress(user_id, p)
                    )

                    # 10. Обновляем задачу
                    task.status_id = 3  # completed
                    task.completed_at = datetime.now()
                    task.result_path = video_path
                    await session.commit()

                    # 11. Отправляем видео (исправленная часть)
                    try:
                        video_input = types.BufferedInputFile.from_file(video_path)
                        await bot.send_video(
                            chat_id=chat_id,
                            video=video_input,
                            caption=f"🎥 Готово! Стиль: {style.style_name}",
                            supports_streaming=True
                        )
                    except Exception as send_error:
                        print(f"Ошибка отправки видео: {send_error}")
                        await bot.send_message(
                            chat_id=chat_id,
                            text="❌ Не удалось отправить видео. Попробуйте позже."
                        )

                except Exception as e:
                    # 12. Обработка ошибок генерации
                    task.status_id = 4  # failed
                    task.completed_at = datetime.now()
                    await session.commit()

                    error_msg = f"❌ Ошибка: {str(e)}"
                    await bot.send_message(chat_id=chat_id, text=error_msg)
                    print(f"Ошибка для user {user_id}: {error_msg}")

            except Exception as e:
                await session.rollback()
                error_msg = f"Ошибка БД: {str(e)}"
                await bot.send_message(chat_id=chat_id, text="⚠️ Ошибка системы")
                print(error_msg)

    except Exception as e:
        error_msg = f"Неожиданная ошибка: {str(e)}"
        await bot.send_message(chat_id=chat_id, text="⚠️ Ошибка системы")
        print(error_msg)
    finally:
        # 13. Очистка временных данных
        user_temp_data.pop(user_id, None)
        progress_tracker.pop(user_id, None)


async def update_progress(user_id: int, progress: int):
    """Обновление прогресса в реальном времени"""
    if user_id not in progress_tracker:
        return

    tracker = progress_tracker[user_id]
    chat_id = tracker.get("chat_id")
    if not chat_id:
        return

    try:
        tracker["progress"] = progress

        if tracker.get("message_id") is None:
            return

        elapsed = int(time() - tracker["start_time"])
        remaining = int((100 - progress) * elapsed / max(1, progress))

        progress_text = (
            f"🔄 Прогресс: {progress}%\n"
            f"⏱ Прошло: {elapsed // 60} мин {elapsed % 60} сек\n"
            f"⏳ Осталось: ~{remaining // 60} мин"
        )

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=tracker["message_id"],
            text=progress_text
        )
    except Exception as e:
        print(f"Ошибка обновления прогресса: {str(e)}")


async def cleanup_old_files():
    """Очистка старых файлов"""
    async with async_session() as session:
        cutoff = datetime.now() - timedelta(days=7)
        await session.execute(delete(Upload).where(Upload.upload_time < cutoff))
        await session.commit()


async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Проверяем, есть ли уже статусы в базе
        existing_statuses = await session.execute(select(TaskStatus))
        if not existing_statuses.scalars().all():
            # Добавляем статусы только если их нет
            statuses = [
                {"id": 1, "status_name": "pending"},
                {"id": 2, "status_name": "processing"},
                {"id": 3, "status_name": "completed"},
                {"id": 4, "status_name": "failed"}
            ]

            for status in statuses:
                session.add(TaskStatus(**status))
            await session.commit()

        # Проверяем и добавляем стили обработки
        existing_styles = await session.execute(select(ProcessingStyle))
        if not existing_styles.scalars().all():
            # Добавляем базовые стили
            styles = [
                {"style_name": "anime", "description": "Аниме стиль"},
                {"style_name": "cyberpunk", "description": "Киберпанк стиль"},
                {"style_name": "impressionism", "description": "Импрессионизм"},
                {"style_name": "pixelart", "description": "Пиксели"}
            ]
            for style in styles:
                session.add(ProcessingStyle(**style))
            await session.commit()

async def on_shutdown():
    """Действия при выключении"""
    scheduler.shutdown()
    await bot.session.close()

async def main():
    await on_startup()
    await dp.start_polling(bot)
    await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())