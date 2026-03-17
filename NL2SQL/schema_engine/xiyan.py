import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from schema_engine.schema_engine import SchemaEngine

def mschema():
    """
     阿里析言中组织Schema的方式
     :return:
    """
    load_dotenv()
    db_uri = os.getenv("DB_URI")
    db_engine = create_engine(db_uri)

    TABLES = [
        'ST_TABLE_D',
        'ST_FIELD_D',
        'ST_PPTN_R',
        'ST_RIVER_R',
        'ST_STBPRP_B',
        'ST_ADDVCD_D',
        'ST_RVFCCH_B',
        'ST_FORECAST_F',
        'ST_HIWRCH_B'
    ]
    SCHEMA_NAME = "dbo"

    schema_engine = SchemaEngine(
        engine=db_engine,
        schema=SCHEMA_NAME,
        include_tables=TABLES
    )

    mschema_obj = schema_engine.mschema
    mschema_str = mschema_obj.to_mschema()
    # 输出控制
    print(mschema_str)
    return mschema_str




if __name__ == '__main__':
    mschema()


