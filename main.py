import os
import datetime
import logging
import json
import shutil
from typing import List, Optional, Dict, Any, Union
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Text, JSON, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import sessionmaker, Session, declarative_base, relationship
from passlib.context import CryptContext
import jwt 
from pydantic import BaseModel

# --- НАСТРОЙКИ ---
SECRET_KEY = "media-quiz-secret-key-2025"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 

SQLALCHEMY_DATABASE_URL = "sqlite:///./quiz.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- МОДЕЛИ БД ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    full_name = Column(String, default="")
    phone = Column(String, default="")
    work = Column(String, default="")
    position = Column(String, default="")
    is_admin = Column(Boolean, default=False)
    avatar = Column(String, nullable=True)
    allowed_attempts = Column(Integer, default=1) # Количество разрешенных попыток

    results = relationship("Result", back_populates="user")

class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text)
    type = Column(String)
    options = Column(JSON, nullable=True)
    correct_answer = Column(JSON, nullable=True)

class Result(Base):
    __tablename__ = "results"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    answers = Column(JSON)
    score = Column(Integer, default=0)
    max_score = Column(Integer, default=0)
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="results")

# --- СХЕМЫ ---
class UserRegister(BaseModel):
    email: str
    password: str
    name: str
    phone: Optional[str] = ""
    work: Optional[str] = ""
    pos: Optional[str] = ""

class UserLogin(BaseModel):
    email: str
    password: str

class Submission(BaseModel):
    answers: Dict[str, Any]

class QuestionOut(BaseModel):
    id: int
    text: str
    type: str
    options: Optional[List[str]] = None

class ResultOut(BaseModel):
    id: int
    score: int
    max_score: int
    submitted_at: datetime.datetime

class AdminResultOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    user_email: str
    user_phone: str # Добавлено
    score: int
    max_score: int
    submitted_at: datetime.datetime
    answers: Dict[str, Any]

# --- APP ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("static/avatars"):
    os.makedirs("static/avatars", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- AUTH ---
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None: raise HTTPException(status_code=401)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.email == email).first()
    if user is None: raise HTTPException(status_code=401)
    return user

# --- СЕДИНГ ВОПРОСОВ ---
def seed_questions(db: Session):
    if db.query(Question).count() > 0:
        return

    questions_data = [
        {"text": "1. Какие предметы нужны для поступления в проект «Медиакласс в московской школе» (несколько вариантов)?", "type": "multiple", "options": ["Литература", "Обществознание", "История", "Иностранный язык"], "correct_answer": ["Литература", "Иностранный язык"]},
        {"text": "2. Вы столкнулись с ситуацией: Выпускник 9-го класса хочет поступить в класс проекта. При этом имеет следующие результаты ОГЭ: математика – 3, русский язык 4, литература 5, иностранный язык 3", "type": "single", "options": ["Да", "Нет"], "correct_answer": ["Нет"]},
        {"text": "3. Вы столкнулись с ситуацией: Выпускник 9-го класса хочет поступить в класс проекта. При этом имеет следующие результаты ОГЭ: математика – 4, русский язык - 4, обществознание - 5, география – 3", "type": "single", "options": ["Да", "Нет"], "correct_answer": ["Да"]},
        {"text": "4. В каких случаях вы НЕ можете зачислить ученика? (несколько вариантов)", "type": "multiple", "options": ["Ученик сдавал доп. ОГЭ: информатика, химия", "Средний балл ОГЭ 4", "Ученик имеет 3 по литературе и английскому", "Ученик после 1 курса колледжа"], "correct_answer": ["Ученик имеет 3 по литературе и английскому", "Ученик после 1 курса колледжа"]},
        {"text": "5. Можно ли осуществить перевод в класс проект 14 января?", "type": "single", "options": ["Да, можно осуществить перевод из профильного класса в класс Проект", "Нет, перевод возможно осуществить только в первом полугодии 10-го класса до 31 декабря"], "correct_answer": ["Нет, перевод возможно осуществить только в первом полугодии 10-го класса до 31 декабря"]},
        {"text": "6. Не менее скольких баллов ЕГЭ нужно по Русскому и двум профильным?", "type": "single", "options": ["Не менее 60 баллов", "Не менее 45 баллов"], "correct_answer": ["Не менее 60 баллов"]},
        {"text": "7. По какому профилю реализуется обучение?", "type": "single", "options": ["Технический", "Естественно-научный", "Гуманитарный", "Универсальный"], "correct_answer": ["Гуманитарный"]},
        {"text": "8. В какой форме осуществляется обучение?", "type": "single", "options": ["Очно", "Заочно", "Очно-заочно", "Дистанционно"], "correct_answer": ["Очно"]},
        {"text": "9. Программы проф. подготовки в колледже (несколько)?", "type": "multiple", "options": ["Оператор видеозаписи", "Фотограф", "Оформитель табло", "Корректор СМИ"], "correct_answer": ["Оператор видеозаписи", "Фотограф", "Оформитель табло"]},
        {"text": "10. Условия завершения обучения (несколько)?", "type": "multiple", "options": ["Не менее 60 баллов ЕГЭ по русскому языку", "Не менее 60 баллов ЕГЭ по двум профильным предметам (каждому) из: литература / иностранный / обществознание", "Посещение обязательных мероприятий не менее 75% часов (в совокупности)", "Не менее 90% посещаемости уроков физкультуры"], "correct_answer": ["Не менее 60 баллов ЕГЭ по русскому языку", "Не менее 60 баллов ЕГЭ по двум профильным предметам (каждому) из: литература / иностранный / обществознание", "Посещение обязательных мероприятий не менее 75% часов (в совокупности)"]},
        {"text": "11. При каких условиях обучающийся получит «Сертификат с отличием»? (несколько вариантов)", "type": "multiple", "options": ["Сумма результатов ЕГЭ (русский + 2 углубленных) не ниже суммы среднегородских баллов", "Победа/призерство в открытой городской научно-практической конференции «Наука для жизни» и/или «Интеллектуальный мегаполис. Потенциал» и/или «Медиатон» за период обучения.", "Обязательное наличие золотого знака ГТО", "Стажирвока в медиацентре ВУЗа"], "correct_answer": ["Сумма результатов ЕГЭ (русский + 2 углубленных) не ниже суммы", "Победа/призерство в открытой городской научно-практической конференции «Наука для жизни» и/или «Интеллектуальный мегаполис. Потенциал» и/или «Медиатон» за период обучения."]},
        {"text": "12. Какова минимальная наполняемость класса для открытия класса Проекта?", "type": "single", "options": ["Не менее 20 человек", "Не менее 22 человек", "Не менее 25 человек", "Не менее 30 человек"], "correct_answer": ["Не менее 25 человек"]},
        {"text": "13. Основная цель проведения Конкурса «Интеллектуальный мегаполис. Потенциал»:", "type": "single", "options": ["Отбор участников на стажировки в медиакомпании", "Диагностика функциональной грамотности и межпредметных связей + независимая оценка подготовки 11-классников предпрофобразования", "Подготовка к ЕГЭ по профильным предметам", "Формирование портфолио достижений для МЭШ"], "correct_answer": ["Диагностика функциональной грамотности и межпредметных связей + независимая оценка подготовки 11-классников предпрофобразования"]},
        {"text": "14. Диапазон баллов для получения диплома победителя в «Интеллектуальный мегаполис. Потенциал»:", "type": "single", "options": ["60–79", "80–99", "100–120", "121–140"], "correct_answer": ["100–120"]},
        {"text": "15. Возможна ли подача апелляций по результатам Конкурса «Интеллектуальный мегаполис. Потенциал»?", "type": "single", "options": ["Да,в течении 3 дней", "Да, в течении недели", "Нет, апелляции не предусмотрены", "Да, Только по практическому этапу"], "correct_answer": ["Нет, аппеляции не предусмотрены"]},
        {"text": "16. На каких предметах базируется теоретический этап направления «Медиа» в Конкурсе «Интеллектуальный мегаполис. Потенциал»?", "type": "single", "options": ["Русский язык, История, Литература", "Литература, Обществознание, Иностранный язык (по выбору)", "Информатика, Математика, Физика", "Биология, Химия"], "correct_answer": ["Литература, Обществознание, Иностранный язык (по выбору)"]},
        {"text": "17. Ситуация. Обучающийся зарегистрирован на сдачу теоретического этапа 13 января 2025 года. Обучающийся по состоянию здоровья не может присутствовать на экзамене. Куда необходимо направить письмо с просьбой перенести экзамен?", "type": "single", "options": ["mediaclass@mpgu.ru", "help@mcko.ru"], "correct_answer": ["help@mcko.ru"]},
        {"text": "18. Ситуация. Ваша школа организовала встречу с представителем медиасферы. Выберите крайний срок, когда куратор может направить лист обратной связи в Проектный офис, чтобы встреча была зачтена в образовательном маршруте.", "type": "single", "options": ["До 31 Мая", "До 1 Июля", "До ЕГЭ"], "correct_answer": ["До 31 Мая"]},
        {"text": "19. Какие обязанности относятся к функциям Куратора Проекта? (несколько вариантов)", "type": "multiple", "options": ["Регистрировать обучающихся на мероприятия партнеров и организовывать их посещение", "Своевременно информировать обучающихся о мероприятиях Проекта, размещенных на порталах","Размещать информацию о ходе реализации Проекта на официальном сайте школы", "Утверждать перечень школ-участников приказом"], "correct_answer": ["Регистрировать обучающихся на мероприятия партнеров и организовывать их посещение", "Своевременно информировать обучающихся о мероприятиях Проекта, размещенных на порталах", "Размещать информацию о ходе реализации Проекта на официальном сайте школы"]},
        {"text": "20. Какие требования предъявляются к педагогам?", "type": "single", "options": ["Стаж не менее 20 лет", "Наличие Свидетельства МЦКО / Ученой степени", "Наличие Второго высшего образования", "Учебник"], "correct_answer": ["Наличие Свидетельства МЦКО / Ученой степени"]},
        {"text": "21. Ситуация. Ученик решил перейти в другую школу, а обучение по программе ПОБГ уже началось. Каков алгоритм действия куратора проекта «Медиакласс в московской школе»?", "type": "single", "options": ["Связываемся в МАХ с представителем колледжа. Объясняем ситуацию", "Составляем на бланке организации информационное письмо с просьбой отчислить обучающегося с указанием наименования колледжа и профессии. Отправляет секретарь через МосЭДО в МЦРПО (на имя директора). Далее дублирование на электронную почту: ГАОУ ДПО МЦРПО, pobg@edu.mos.ru, ИРПО ГАОУ ВО МГПУ, Медиакласс: mediaclass@mgpu.ru, официальная почта колледжа"], "correct_answer": ["Составляем на бланке организации информационное письмо с просьбой отчислить обучающегося с указанием наименования колледжа и профессии. Отправляет секретарь через МосЭДО в МЦРПО (на имя директора). Далее дублирование на электронную почту: ГАОУ ДПО МЦРПО, pobg@edu.mos.ru, ИРПО ГАОУ ВО МГПУ, Медиакласс: mediaclass@mgpu.ru, официальная почта колледжа"]}
    ]

    for q in questions_data:
        db_q = Question(
            text=q['text'],
            type=q['type'],
            options=q['options'],
            correct_answer=q['correct_answer']
        )
        db.add(db_q)
    db.commit()

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    if not db.query(User).filter(User.email == "admin@admin.com").first():
        try:
            admin = User(email="admin@admin.com", hashed_password=pwd_context.hash("admin"), full_name="Администратор", is_admin=True, allowed_attempts=999)
            db.add(admin)
            db.commit()
        except: pass
    
    seed_questions(db)
    db.close()

# --- ЭНДПОИНТЫ ---

@app.get("/", response_class=HTMLResponse)
def index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Загрузите файл index.html</h1>"

@app.post("/register")
def register(data: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email занят")
    
    user = User(
        email=data.email,
        hashed_password=pwd_context.hash(data.password),
        full_name=data.name,
        phone=data.phone,
        work=data.work,
        position=data.pos,
        allowed_attempts=1 # По умолчанию 1 попытка
    )
    db.add(user)
    db.commit()
    return {"msg": "OK"}

@app.post("/login")
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not pwd_context.verify(data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверные данные")
    
    token = jwt.encode({"sub": user.email, "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token}

@app.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Получаем историю тестов
    history = []
    # Сортируем по дате, чтобы нумерация была хронологической
    sorted_results = sorted(user.results, key=lambda x: x.submitted_at)
    
    for idx, r in enumerate(sorted_results):
        history.append({
            "id": r.id,
            "attempt_number": idx + 1, # Персональный номер попытки (1, 2, 3...)
            "score": r.score,
            "max_score": r.max_score,
            "submitted_at": r.submitted_at
        })
    
    can_retake = len(user.results) < user.allowed_attempts

    return {
        "full_name": user.full_name, 
        "email": user.email, 
        "is_admin": user.is_admin, 
        "work": user.work, 
        "avatar": user.avatar,
        "position": user.position,
        "history": history,
        "can_retake": can_retake
    }

@app.post("/users/me/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    safe_filename = f"{user.id}_{file.filename}".replace(" ", "_")
    file_path = f"static/avatars/{safe_filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    user.avatar = "/" + file_path
    db.commit()
    db.refresh(user)
    return {"url": user.avatar}

@app.get("/questions", response_model=List[QuestionOut])
def get_qs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Проверка на право пересдачи
    if len(user.results) >= user.allowed_attempts and not user.is_admin:
        raise HTTPException(status_code=400, detail="У вас закончились попытки")
    return db.query(Question).all()

@app.post("/submit")
def submit_quiz(sub: Submission, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if len(user.results) >= user.allowed_attempts and not user.is_admin:
        raise HTTPException(status_code=400, detail="У вас закончились попытки")

    questions = db.query(Question).all()
    q_map = {q.id: q for q in questions}
    score = 0
    max_score = 0
    correct_answers_map = {}

    for q_id_str, user_ans in sub.answers.items():
        q_id = int(q_id_str)
        if q_id not in q_map: continue
        q = q_map[q_id]
        correct = q.correct_answer or []
        is_correct = False
        
        if q.type == 'single':
            if isinstance(correct, list) and len(correct) > 0:
                if user_ans == correct[0]: is_correct = True
            elif user_ans == correct: is_correct = True
        elif q.type == 'multiple':
            if isinstance(user_ans, list) and isinstance(correct, list) and set(user_ans) == set(correct):
                is_correct = True
        elif q.type == 'open':
             if len(str(user_ans)) > 2: is_correct = True

        if is_correct: score += 1
        max_score += 1
        correct_answers_map[q_id] = correct

    res = Result(user_id=user.id, answers=sub.answers, score=score, max_score=max_score)
    db.add(res)
    db.commit()
    return {"score": score, "max_score": max_score, "correct_answers": correct_answers_map}

@app.get("/admin/results", response_model=List[AdminResultOut])
def admin_res(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin: raise HTTPException(status_code=403, detail="Только для админов")
    results = db.query(Result).all()
    out = []
    for r in results:
        out.append({
            "id": r.id, 
            "user_id": r.user.id,
            "user_name": r.user.full_name, 
            "user_email": r.user.email, 
            "user_phone": r.user.phone, # Добавлено
            "score": r.score, 
            "max_score": r.max_score, 
            "submitted_at": r.submitted_at, 
            "answers": r.answers
        })
    return out

# Новые функции админа
@app.post("/admin/allow_retry/{user_id}")
def allow_retry(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin: raise HTTPException(status_code=403)
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        # ЛОГИКА ИЗМЕНЕНА: Лимит = (количество реально пройденных попыток) + 1
        # Это дает пользователю ровно одну новую попытку, независимо от старого лимита
        passed_attempts = len(target_user.results)
        target_user.allowed_attempts = passed_attempts + 1
        db.commit()
    return {"status": "ok"}

@app.post("/admin/issue_certificate/{user_id}")
def issue_cert(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin: raise HTTPException(status_code=403)
    # Тут будет логика генерации и отправки PDF
    # Пока заглушка
    return {"status": "sent", "message": "Сертификат отправлен на почту"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", reload=True)
