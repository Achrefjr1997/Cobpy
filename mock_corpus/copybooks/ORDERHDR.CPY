      * Order header record layout
      * Used by ORDENTRY and ORDREPT
       01  ORDER-RECORD.
           05  OR-ORDER-NUM       PIC X(15).
           05  OR-CUSTOMER-ID     PIC X(10).
           05  OR-ORDER-DATE      PIC X(10).
           05  OR-STATUS          PIC X(01).
               88  OR-PENDING     VALUE "P".
               88  OR-SHIPPED     VALUE "S".
               88  OR-CANCELLED   VALUE "C".
           05  OR-LINE-COUNT      PIC 9(03).
           05  OR-LINE-ITEMS OCCURS 50.
               10  ORL-ITEM-NUM   PIC X(15).
               10  ORL-QUANTITY   PIC 9(05).
               10  ORL-UNIT-PRICE PIC 9(07)V99.
               10  ORL-EXT-PRICE  PIC 9(09)V99.
