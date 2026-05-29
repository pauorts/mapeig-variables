import sys
import logging
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import Hospital
from app.services.variables_metrics import update_all_metrics_ccc, update_all_metrics_cha

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Map of hosp acronym → acronim column value in Hospital table
HOSP_ACRONIMS = {
    'jx': 'JX',
    'vc': 'VC',
    'cha': 'CHA',
}

def _get_hospital_id(db: Session, hosp_key: str) -> int:
    acronim = HOSP_ACRONIMS[hosp_key]
    hospital = db.query(Hospital).filter(Hospital.acronim == acronim).first()
    if hospital is None:
        raise ValueError(f"Hospital amb acronim '{acronim}' no trobat a la BD.")
    return hospital.id

def main():
    logger.info("Starting metrics update job...")

    db: Session = SessionLocal()
    try:
        hospital_id = _get_hospital_id(db, 'jx')
        update_all_metrics_ccc(db, hosp='jx', hospital_id=hospital_id)
        logger.info("Metrics JX update completed successfully.")
    except Exception as e:
        logger.error(f"Error updating metrics JX: {e}")
        sys.exit(1)
    finally:
        db.close()

    db: Session = SessionLocal()
    try:
        hospital_id = _get_hospital_id(db, 'vc')
        update_all_metrics_ccc(db, hosp='vc', hospital_id=hospital_id)
        logger.info("Metrics VC update completed successfully.")
    except Exception as e:
        logger.error(f"Error updating metrics VC: {e}")
        sys.exit(1)
    finally:
        db.close()

    # db: Session = SessionLocal()
    # try:
    #     hospital_id = _get_hospital_id(db, 'cha')
    #     update_all_metrics_cha(db, hospital_id=hospital_id)
    #     logger.info("Metrics CHA update completed successfully.")
    # except Exception as e:
    #     logger.error(f"Error updating metrics CHA: {e}")
    #     sys.exit(1)
    # finally:
    #     db.close()

if __name__ == "__main__":
    main()