from sqlalchemy import create_engine
from NL2SQL.config.settings import DB_SCHEMA, DB_URI, INCLUDE_TABLES
from NL2SQL.schema_engine.schema_engine import SchemaEngine

def mschema():
    """
     阿里析言中组织Schema的方式
     :return:
    """
    db_engine = create_engine(DB_URI)

    schema_engine = SchemaEngine(
        engine=db_engine,
        schema=DB_SCHEMA,
        include_tables=INCLUDE_TABLES,
    )

    mschema_obj = schema_engine.mschema
    mschema_str = mschema_obj.to_mschema()
    # 输出控制
    print(mschema_str)
    return mschema_str




if __name__ == '__main__':
    mschema()


