      * Customer master record layout
      * Used by VALCUST and ORDENTRY
       01  CUSTOMER-MASTER.
           05  CM-CUSTOMER-ID      PIC X(10).
           05  CM-NAME             PIC X(30).
           05  CM-ADDRESS.
               10  CM-STREET       PIC X(40).
               10  CM-CITY         PIC X(20).
               10  CM-STATE        PIC X(02).
               10  CM-ZIP          PIC X(10).
           05  CM-CREDIT-LIMIT    PIC 9(07)V99.
           05  CM-BALANCE         PIC 9(07)V99.
           05  CM-BALANCE-AVAIL   PIC 9(07)V99.
           05  CM-STATUS          PIC X(01).
               88  CM-ACTIVE      VALUE "A".
               88  CM-INACTIVE    VALUE "I".
               88  CM-FROZEN      VALUE "F".
