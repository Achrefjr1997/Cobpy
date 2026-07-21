      * Common status and error messages
       01  MSG-CUST-FOUND       PIC X(60)
                                 VALUE "Customer found and active".
       01  MSG-CUST-NOT-FOUND   PIC X(60)
                                 VALUE "Customer not found".
       01  MSG-CUST-FROZEN      PIC X(60)
                                 VALUE "Customer account is frozen".
       01  MSG-CUST-CREDIT-EXCEEDED
                                 PIC X(60)
                                 VALUE "Customer credit limit exceeded".
       01  MSG-INV-FOUND        PIC X(60)
                                 VALUE "Inventory item found".
       01  MSG-INV-NOT-FOUND    PIC X(60)
                                 VALUE "Inventory item not found".
       01  MSG-INV-LOW-STOCK    PIC X(60)
                                 VALUE "Warning: inventory low on stock".
       01  MSG-ORDER-CREATED    PIC X(60)
                                 VALUE "Order created successfully".
       01  WS-RETURN-CODE       PIC 9(02).
           88  RC-SUCCESS       VALUE 00.
           88  RC-NOT-FOUND     VALUE 01.
           88  RC-VALIDATION-ERR VALUE 02.
           88  RC-SYSTEM-ERR    VALUE 99.
