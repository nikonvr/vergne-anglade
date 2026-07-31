import logging
from sqlalchemy.orm import Session
from src.core.models import Act, Person
from src.database.models import DBAct, DBPerson

class ActRepository:
    def __init__(self, session: Session):
        self.session = session

    def save_act(self, act: Act) -> int:
        db_act = DBAct(
            act_type=act.act_type,
            date=act.date,
            location=act.location,
            confidence_score=act.confidence_score,
            source_text=act.source_text,
            source_type=act.source_type,
            url_source=act.url_source,
            reliability_score=act.reliability_score
        )
        for p in act.persons:
            db_person = DBPerson(first_name=p.first_name, last_name=p.last_name, role=p.role, age=p.age, occupation=p.occupation)
            db_act.persons.append(db_person)
        self.session.add(db_act)
        self.session.commit()
        self.session.refresh(db_act)
        return db_act.id

    def get_all_acts(self) -> list[Act]:
        db_acts = self.session.query(DBAct).all()
        acts = []
        for db_act in db_acts:
            persons = [
                Person(
                    first_name=p.first_name,
                    last_name=p.last_name,
                    role=p.role,
                    age=p.age,
                    occupation=p.occupation,
                )
                for p in db_act.persons
            ]
            act = Act(
                act_type=db_act.act_type,
                date=db_act.date,
                location=db_act.location,
                persons=persons,
                confidence_score=db_act.confidence_score,
                source_text=db_act.source_text,
                source_type=db_act.source_type or "OCR_CANTAL",
                url_source=db_act.url_source,
                reliability_score=db_act.reliability_score if db_act.reliability_score is not None else 1.0,
            )
            acts.append(act)
        return acts