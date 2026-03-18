from sqlalchemy import create_engine, text


def main() -> None:
    engine = create_engine(
        "sqlite:///./matrix_marketing.db",
        connect_args={"check_same_thread": False},
    )

    with engine.begin() as conn:
        # Добавляем колонку total_earned, если её ещё нет
        conn.execute(
            text("ALTER TABLE users ADD COLUMN total_earned FLOAT DEFAULT 0")
        )

    print("Column total_earned added in SQLite.")


if __name__ == "__main__":
    main()

from sqlalchemy import create_engine, text

engine = create_engine('sqlite:///./matrix_marketing.db', connect_args={'check_same_thread': False})

with engine.begin() as conn:
    conn.execute(text('ALTER TABLE users ADD COLUMN total_earned FLOAT DEFAULT 0'))

print("Column total_earned added (or already exists).")
