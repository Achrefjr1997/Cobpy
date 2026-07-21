       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDREPT.

      * Generates an order status report.
      * Uses table iteration (OCCURS), STRING, 88-level conditions,
      * and PERFORM loops to produce a formatted summary.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY ORDERHDR.
       COPY MSGS.

       01  WS-INDEX                 PIC 9(03).
       01  WS-LINE-BUFFER           PIC X(80).
       01  WS-TOTAL-ORDERS          PIC 9(05).
       01  WS-TOTAL-PENDING         PIC 9(05).
       01  WS-TOTAL-SHIPPED         PIC 9(05).
       01  WS-TOTAL-AMOUNT          PIC 9(11)V99.

       PROCEDURE DIVISION.
       MAIN.
           DISPLAY "========================================".
           DISPLAY "ORDER STATUS REPORT".
           DISPLAY "========================================".

           MOVE 0 TO WS-TOTAL-ORDERS.
           MOVE 0 TO WS-TOTAL-PENDING.
           MOVE 0 TO WS-TOTAL-SHIPPED.
           MOVE 0 TO WS-TOTAL-AMOUNT.

      * First order
           MOVE "ORD001" TO OR-ORDER-NUM.
           MOVE "CUST001" TO OR-CUSTOMER-ID.
           MOVE "2025-01-15" TO OR-ORDER-DATE.
           SET OR-SHIPPED TO TRUE.
           MOVE 2 TO OR-LINE-COUNT.
           MOVE "ITEM001" TO ORL-ITEM-NUM(1).
           MOVE 5 TO ORL-QUANTITY(1).
           MOVE 150000 TO ORL-EXT-PRICE(1).
           MOVE "ITEM002" TO ORL-ITEM-NUM(2).
           MOVE 3 TO ORL-QUANTITY(2).
           MOVE 75000 TO ORL-EXT-PRICE(2).

           PERFORM PRINT-ORDER-HEADER.
           PERFORM VARYING WS-INDEX FROM 1 BY 1
                   UNTIL WS-INDEX > OR-LINE-COUNT
               PERFORM PRINT-DETAIL-LINE
               ADD ORL-EXT-PRICE(WS-INDEX) TO WS-TOTAL-AMOUNT
           END-PERFORM.

           ADD 1 TO WS-TOTAL-ORDERS.
           IF OR-SHIPPED
               ADD 1 TO WS-TOTAL-SHIPPED.

      * Second order
           MOVE "ORD002" TO OR-ORDER-NUM.
           MOVE "CUST002" TO OR-CUSTOMER-ID.
           MOVE "2025-01-20" TO OR-ORDER-DATE.
           SET OR-PENDING TO TRUE.
           MOVE 1 TO OR-LINE-COUNT.
           MOVE "ITEM003" TO ORL-ITEM-NUM(1).
           MOVE 10 TO ORL-QUANTITY(1).
           MOVE 200000 TO ORL-EXT-PRICE(1).

           PERFORM PRINT-ORDER-HEADER.
           PERFORM VARYING WS-INDEX FROM 1 BY 1
                   UNTIL WS-INDEX > OR-LINE-COUNT
               PERFORM PRINT-DETAIL-LINE
               ADD ORL-EXT-PRICE(WS-INDEX) TO WS-TOTAL-AMOUNT
           END-PERFORM.

           ADD 1 TO WS-TOTAL-ORDERS.
           IF OR-PENDING
               ADD 1 TO WS-TOTAL-PENDING.

      * Print summary
           DISPLAY "========================================".
           DISPLAY "SUMMARY:".
           DISPLAY "  Total Orders:  " WS-TOTAL-ORDERS.
           DISPLAY "  Pending:       " WS-TOTAL-PENDING.
           DISPLAY "  Shipped:       " WS-TOTAL-SHIPPED.
           DISPLAY "  Total Amount:  " WS-TOTAL-AMOUNT.
           DISPLAY "========================================".

           GOBACK.

       PRINT-ORDER-HEADER.
           STRING "Order " DELIMITED BY SIZE
                  OR-ORDER-NUM DELIMITED BY SPACE
                  "  Customer: " DELIMITED BY SIZE
                  OR-CUSTOMER-ID DELIMITED BY SPACE
                  "  Date: " DELIMITED BY SIZE
                  OR-ORDER-DATE DELIMITED BY SPACE
                  "  Status: " DELIMITED BY SIZE
                  OR-STATUS DELIMITED BY SIZE
             INTO WS-LINE-BUFFER
           END-STRING.
           DISPLAY WS-LINE-BUFFER.
           DISPLAY "  Line Items:".

       PRINT-DETAIL-LINE.
           STRING "    " DELIMITED BY SIZE
                  ORL-ITEM-NUM(WS-INDEX) DELIMITED BY SPACE
                  "  Qty: " DELIMITED BY SIZE
                  ORL-QUANTITY(WS-INDEX) DELIMITED BY SIZE
                  "  Ext: " DELIMITED BY SIZE
                  ORL-EXT-PRICE(WS-INDEX) DELIMITED BY SIZE
             INTO WS-LINE-BUFFER
           END-STRING.
           DISPLAY WS-LINE-BUFFER.
