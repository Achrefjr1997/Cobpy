       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCTAX.

      * Calculates sales tax based on progressive brackets.
      * Receives gross amount and returns calculated tax.
      * Uses EVALUATE for bracket selection and COMPUTE ROUNDED.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TAX-RATE          PIC V999.
       01  WS-TAX-BRACKET       PIC 9(01).
           88  BRACKET-LOW      VALUE 1.
           88  BRACKET-MEDIUM   VALUE 2.
           88  BRACKET-HIGH     VALUE 3.

       LINKAGE SECTION.
       01  LS-GROSS-AMOUNT      PIC 9(09)V99.
       01  LS-TAX-AMOUNT        PIC 9(09)V99.

       PROCEDURE DIVISION USING LS-GROSS-AMOUNT LS-TAX-AMOUNT.
       MAIN.
           EVALUATE TRUE
               WHEN LS-GROSS-AMOUNT <= 10000
                   MOVE 1 TO WS-TAX-BRACKET
                   MOVE 0.050 TO WS-TAX-RATE
               WHEN LS-GROSS-AMOUNT <= 50000
                   MOVE 2 TO WS-TAX-BRACKET
                   MOVE 0.120 TO WS-TAX-RATE
               WHEN OTHER
                   MOVE 3 TO WS-TAX-BRACKET
                   MOVE 0.250 TO WS-TAX-RATE
           END-EVALUATE.

           COMPUTE LS-TAX-AMOUNT ROUNDED =
               LS-GROSS-AMOUNT * WS-TAX-RATE.

           IF LS-TAX-AMOUNT = 0
               MOVE 1 TO LS-TAX-AMOUNT
           END-IF.

           GOBACK.
