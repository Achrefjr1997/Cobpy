import { loader } from "@monaco-editor/react";

const cobolMonarch: Record<string, unknown> = {
  defaultToken: "text",
  ignoreCase: true,
  tokenizer: {
    root: [
      [/^\s{6}\*.*$/, "comment"],
      [/\*>.*$/, "comment"],
      [/".*?"/, "string"],
      [/'.*?'/, "string"],

      [/PIC\b/, "keyword.pic"],
      [/PICTURE\b/, "keyword.pic"],

      [/COMPUTE\b/, "keyword.control"],
      [/PERFORM\b/, "keyword.control"],
      [/IF\b/, "keyword.control"],
      [/END-IF\b/, "keyword.control"],
      [/ELSE\b/, "keyword.control"],
      [/THEN\b/, "keyword.control"],
      [/MOVE\b/, "keyword.control"],
      [/SET\b/, "keyword.control"],
      [/EVALUATE\b/, "keyword.control"],
      [/WHEN\b/, "keyword.control"],
      [/ALSO\b/, "keyword.control"],
      [/DISPLAY\b/, "keyword.io"],
      [/ACCEPT\b/, "keyword.io"],
      [/STOP\b/, "keyword.control"],
      [/GO\b/, "keyword.control"],
      [/TO\b/, "keyword.storage"],
      [/CALL\b/, "keyword.control"],
      [/EXIT\b/, "keyword.control"],
      [/RETURN\b/, "keyword.control"],
      [/ADD\b/, "keyword.control"],
      [/SUBTRACT\b/, "keyword.control"],
      [/MULTIPLY\b/, "keyword.control"],
      [/DIVIDE\b/, "keyword.control"],
      [/INITIALIZE\b/, "keyword.control"],
      [/INSPECT\b/, "keyword.control"],
      [/STRING\b/, "keyword.control"],
      [/UNSTRING\b/, "keyword.control"],
      [/SEARCH\b/, "keyword.control"],
      [/CONTINUE\b/, "keyword.control"],

      [/IDENTIFICATION\b/, "keyword.section"],
      [/ID\b/, "keyword.section"],
      [/DIVISION\b/, "keyword.section"],
      [/SECTION\b/, "keyword.section"],
      [/DATA\b/, "keyword.section"],
      [/PROCEDURE\b/, "keyword.section"],
      [/ENVIRONMENT\b/, "keyword.section"],
      [/WORKING-STORAGE\b/, "keyword.section"],
      [/LINKAGE\b/, "keyword.section"],
      [/LOCAL-STORAGE\b/, "keyword.section"],
      [/FILE\b/, "keyword.section"],
      [/FD\b/, "keyword.section"],

      [/PROGRAM-ID\b/, "keyword.decl"],
      [/FUNCTION-ID\b/, "keyword.decl"],
      [/END PROGRAM\b/, "keyword.decl"],
      [/END FUNCTION\b/, "keyword.decl"],
      [/END\b/, "keyword.decl"],

      [/SELECT\b/, "keyword.storage"],
      [/ASSIGN\b/, "keyword.storage"],
      [/FROM\b/, "keyword.storage"],
      [/USING\b/, "keyword.storage"],
      [/THRU\b/, "keyword.storage"],
      [/THROUGH\b/, "keyword.storage"],
      [/VARYING\b/, "keyword.storage"],
      [/UNTIL\b/, "keyword.storage"],
      [/AFTER\b/, "keyword.storage"],
      [/BEFORE\b/, "keyword.storage"],
      [/BY\b/, "keyword.storage"],
      [/WITH\b/, "keyword.storage"],
      [/FOR\b/, "keyword.storage"],
      [/IN\b/, "keyword.storage"],
      [/OF\b/, "keyword.storage"],
      [/IS\b/, "keyword.storage"],
      [/ARE\b/, "keyword.storage"],
      [/NOT\b/, "keyword.storage"],
      [/OR\b/, "keyword.storage"],
      [/AND\b/, "keyword.storage"],

      [/OCCURS\b/, "keyword.storage"],
      [/REDEFINES\b/, "keyword.storage"],
      [/VALUES?\b/, "keyword.storage"],
      [/JUST(IFIED)?\b/, "keyword.storage"],
      [/BLANK WHEN ZERO\b/, "keyword.storage"],
      [/SIGN\b/, "keyword.storage"],
      [/LEADING\b/, "keyword.storage"],
      [/TRAILING\b/, "keyword.storage"],

      [/OPEN\b/, "keyword.io"],
      [/CLOSE\b/, "keyword.io"],
      [/READ\b/, "keyword.io"],
      [/WRITE\b/, "keyword.io"],
      [/REWRITE\b/, "keyword.io"],
      [/DELETE\b/, "keyword.io"],
      [/START\b/, "keyword.io"],

      [/\b0[1-9]\b/, "number.level"],
      [/\b[1-9][0-9]\b/, "number.level"],
      [/\b\d+\b/, "number"],
      [/\d+\.\d+/, "number.float"],

      [/[A-Za-z][A-Za-z0-9-]*/, "identifier"],
    ],
  },
};

let registered = false;

export function registerCobolLanguage(): void {
  if (registered) return;
  registered = true;

  loader.init().then((monaco) => {
    monaco.languages.register({ id: "cobol" });
    monaco.languages.setMonarchTokensProvider("cobol", cobolMonarch as any); // eslint-disable-line @typescript-eslint/no-explicit-any
  });
}
