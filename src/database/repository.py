import logging
from typing import List, Optional

from sqlalchemy.orm import Session, selectinload

from src.core.models import Act, Person
from src.database.models import DBAct, DBPerson

logger = logging.getLogger("certus.database")


class ActRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ conversions

    @staticmethod
    def _to_db_act(act: Act) -> DBAct:
        """Construit l'entité ORM correspondant à un acte (sans l'ajouter à la session)."""
        db_act = DBAct(
            act_type=act.act_type,
            date=act.date,
            location=act.location,
            confidence_score=act.confidence_score,
            source_text=act.source_text,
            source_type=act.source_type,
            url_source=act.url_source,
            reliability_score=act.reliability_score,
            is_simulated=bool(act.is_simulated),
            family_id=act.family_id,
        )
        for p in act.persons:
            db_act.persons.append(
                DBPerson(
                    source_id=p.source_id,
                    first_name=p.first_name,
                    last_name=p.last_name,
                    role=p.role,
                    age=p.age,
                    occupation=p.occupation,
                    sex=p.sex,
                    birth_date=p.birth_date,
                    birth_place=p.birth_place,
                    death_date=p.death_date,
                    death_place=p.death_place,
                )
            )
        return db_act

    @staticmethod
    def _to_act(db_act: DBAct) -> Act:
        """Reconstruit le modèle métier, id SQL et champs d'état civil compris."""
        persons = [
            Person(
                source_id=p.source_id,
                first_name=p.first_name,
                last_name=p.last_name,
                role=p.role,
                age=p.age,
                occupation=p.occupation,
                sex=p.sex,
                birth_date=p.birth_date,
                birth_place=p.birth_place,
                death_date=p.death_date,
                death_place=p.death_place,
            )
            for p in db_act.persons
        ]
        return Act(
            id=db_act.id,
            act_type=db_act.act_type,
            date=db_act.date,
            location=db_act.location,
            persons=persons,
            confidence_score=db_act.confidence_score,
            source_text=db_act.source_text,
            source_type=db_act.source_type or "GEDCOM_HEREDIS",
            url_source=db_act.url_source,
            reliability_score=db_act.reliability_score if db_act.reliability_score is not None else 1.0,
            is_simulated=bool(db_act.is_simulated),
            family_id=db_act.family_id,
        )

    # ------------------------------------------------------------------ écritures

    def save_act(self, act: Act, commit: bool = True) -> int:
        """Persiste un acte et retourne sa clé primaire.

        commit=False permet à l'appelant de regrouper plusieurs actes dans une seule
        transaction (voir save_acts) : un commit par acte est le principal coût des imports.
        """
        db_act = self._to_db_act(act)
        self.session.add(db_act)
        # flush() suffit à obtenir la clé primaire, sans le coût d'un commit + refresh.
        self.session.flush()
        act_id = db_act.id
        if commit:
            self.session.commit()
        act.id = act_id
        return act_id

    def save_acts(self, acts: List[Act]) -> List[int]:
        """Persiste un lot d'actes avec UN SEUL commit et retourne les clés primaires."""
        if not acts:
            return []
        db_acts = [self._to_db_act(act) for act in acts]
        self.session.add_all(db_acts)
        self.session.flush()
        ids = [db_act.id for db_act in db_acts]
        self.session.commit()
        for act, act_id in zip(acts, ids):
            act.id = act_id
        logger.info("%d actes enregistrés en un commit.", len(ids))
        return ids

    # ------------------------------------------------------------------ lectures

    def get_all_acts(self) -> List[Act]:
        """Tous les actes, triés par clé primaire, avec Act.id renseigné."""
        db_acts = (
            self.session.query(DBAct)
            .options(selectinload(DBAct.persons))  # évite N+1 requêtes sur les personnes
            .order_by(DBAct.id)
            .all()
        )
        return [self._to_act(db_act) for db_act in db_acts]

    def get_act_by_id(self, act_id: int) -> Optional[Act]:
        """Recherche directe par clé primaire (aucun parcours de liste)."""
        db_act = self.session.get(DBAct, act_id)
        return self._to_act(db_act) if db_act else None

    def count_acts(self) -> int:
        """Nombre d'actes en base (sans charger les objets)."""
        return self.session.query(DBAct).count()
