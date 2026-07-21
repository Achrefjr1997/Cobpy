      * Inventory item record layout
      * Used by ORDENTRY
       01  INVENTORY-ITEM.
           05  II-ITEM-NUM        PIC X(15).
           05  II-DESCRIPTION     PIC X(40).
           05  II-ON-HAND         PIC 9(07).
           05  II-REORDER-POINT   PIC 9(07).
           05  II-UNIT-PRICE      PIC 9(07)V99.
           05  II-WAREHOUSE-INFO.
               10  II-WH-CODE     PIC X(03).
               10  II-WH-BIN      PIC X(05).
           05  II-CATEGORY        PIC X(03).
               88  II-CAT-ELEC    VALUE "ELE".
               88  II-CAT-OFFICE  VALUE "OFF".
               88  II-CAT-CLOTH   VALUE "CLO".
