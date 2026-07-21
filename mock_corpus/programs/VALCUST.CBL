       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALCUST.

      * Validates a customer by checking status and credit availability.
      * Uses LINKAGE SECTION to receive input and return results.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTMAST.
       COPY MSGS.

       LINKAGE SECTION.
       01  LS-CUSTOMER-ID       PIC X(10).
       01  LS-RESULT.
           05  LS-VALID-FLAG    PIC X(01).
               88  LS-VALID     VALUE "Y".
               88  LS-INVALID   VALUE "N".
           05  LS-MESSAGE       PIC X(60).
           05  LS-CREDIT-AVAIL  PIC 9(07)V99.

       PROCEDURE DIVISION USING LS-CUSTOMER-ID LS-RESULT.
       MAIN.
           IF LS-CUSTOMER-ID = SPACES
               MOVE "N" TO LS-VALID-FLAG
               MOVE "Customer ID cannot be empty" TO LS-MESSAGE
               GOBACK
           END-IF.

           IF CM-ACTIVE
               COMPUTE LS-CREDIT-AVAIL =
                   CM-CREDIT-LIMIT - CM-BALANCE
               IF LS-CREDIT-AVAIL > 0
                   MOVE "Y" TO LS-VALID-FLAG
                   MOVE MSG-CUST-FOUND TO LS-MESSAGE
               ELSE
                   MOVE "N" TO LS-VALID-FLAG
                   MOVE MSG-CUST-CREDIT-EXCEEDED TO LS-MESSAGE
               END-IF
           ELSE
               MOVE "N" TO LS-VALID-FLAG
               IF CM-FROZEN
                   MOVE MSG-CUST-FROZEN TO LS-MESSAGE
               ELSE
                   MOVE MSG-CUST-NOT-FOUND TO LS-MESSAGE
               END-IF
           END-IF.

           GOBACK.
