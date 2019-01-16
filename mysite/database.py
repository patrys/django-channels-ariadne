from gino import Gino

db = Gino()


async def init_database():
    await db.set_bind("postgresql://localhost/gino")
    await db.gino.create_all()


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer(), primary_key=True)
    title = db.Column(db.String())
    body = db.Column(db.Text())
