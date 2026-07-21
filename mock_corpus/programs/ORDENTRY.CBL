       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDENTRY.

      * Main order entry program.
      * Validates customer, creates order with line items,
      * calculates tax, and produces the final total.
      * Exercises CALL USING, PERFORM VARYING, COPY, STRING, MULTIPLY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY ORDERHDR.
       COPY CUSTMAST.
       COPY MSGS.

       01  WS-INDEX             PIC 9(03).
       01  WS-LINE-TOTAL        PIC 9(09)V99.
       01  WS-ORDER-TOTAL       PIC 9(09)V99.
       01  WS-TAX-AMOUNT        PIC 9(09)V99.
       01  WS-GROSS-AMOUNT      PIC 9(09)V99.
       01  WS-VALID-FLAG        PIC X(01).
       01  WS-VALID-MSG         PIC X(60).
       01  WS-CREDIT-AVAIL      PIC 9(07)V99.

       PROCEDURE DIVISION.
       MAIN.
           DISPLAY "Order Entry System Starting".

           MOVE "CUST001" TO OR-CUSTOMER-ID.
           MOVE "ORD-20250115" TO OR-ORDER-NUM.
           MOVE "2025-01-15" TO OR-ORDER-DATE.
           SET OR-PENDING TO TRUE.

           CALL "VALCUST" USING OR-CUSTOMER-ID WS-VALID-FLAG
                               WS-VALID-MSG WS-CREDIT-AVAIL.

           IF WS-VALID-FLAG = "Y"
               DISPLAY "Customer validated: " WS-VALID-MSG

               MOVE 2 TO OR-LINE-COUNT

               MOVE "ITEM001" TO ORL-ITEM-NUM(1)
               MOVE 5 TO ORL-QUANTITY(1)
               MOVE 1500 TO ORL-UNIT-PRICE(1)
               MULTIPLY ORL-QUANTITY(1) BY ORL-UNIT-PRICE(1)
                   GIVING ORL-EXT-PRICE(1)

               MOVE "ITEM002" TO ORL-ITEM-NUM(2)
               MOVE 3 TO ORL-QUANTITY(2)
               MOVE 2500 TO ORL-UNIT-PRICE(2)
               MULTIPLY ORL-QUANTITY(2) BY ORL-UNIT-PRICE(2)
                   GIVING ORL-EXT-PRICE(2)

               MOVE 0 TO WS-ORDER-TOTAL
               PERFORM VARYING WS-INDEX FROM 1 BY 1
                       UNTIL WS-INDEX > OR-LINE-COUNT
                   ADD ORL-EXT-PRICE(WS-INDEX) TO WS-ORDER-TOTAL
               END-PERFORM

               MOVE WS-ORDER-TOTAL TO WS-GROSS-AMOUNT
               CALL "CALCTAX" USING WS-GROSS-AMOUNT WS-TAX-AMOUNT

               ADD WS-TAX-AMOUNT TO WS-ORDER-TOTAL
               DISPLAY "Order " OR-ORDER-NUM " created"
               DISPLAY "Total with tax: " WS-ORDER-TOTAL
               MOVE "Order created successfully" TO WS-VALID-MSG
           ELSE
               DISPLAY "Order rejected: " WS-VALID-MSG
           END-IF.

           GOBACK.
