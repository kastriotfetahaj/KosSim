grammar Jitterish;

main: func* query* EOF;


primary_expr
    : '(' expr ')'  # RawPrimaryExpr
    | NAME  # Named
    | INT  # ConstantInt
    | ('null' | 'true' | 'false' | STRING_LITERAL)  # ConstantExpr
    | '[' (expr ','?) * ']'  # ArrayExpr
    | '{' (STRING_LITERAL ':' expr ','?)* '}'  # ObjectExpr
    ;

unary_expr
    : left=unary_expr '[' rght=expr ']'  # PropertyGet
    | callee=NAME '(' (expr (',' expr)* ','?)? ')'  # CallExpr
    | op=('!' | '-' | 'len' | 'defined') unary_expr  # UnaryOp
    | primary_expr  # RawExpr
    ;

assignable_expr  // left side of an assignment
    : NAME  # AssignToNamed
    | left=unary_expr '[' right=expr ']'  # AssignToProperty
    | left=unary_expr '[' '+' ']'  # AssignAppend
    ;

expr: unary_expr  # UnaryExpr
    | left=expr op=('*' | '/') rght=expr  # BinaryOp
    | left=expr op=('+' | '-') rght=expr  # BinaryOp
    | left=expr op=('==' | '!=' | '<' | '>' | '<=' | '>=') rght=expr  # BinaryOp
    | left=expr op=('||' | '&&' | '?:') rght=expr  # BinaryOp
    | left=assignable_expr '=' rght=expr  # Assignment
    ;

stmt: expr ';'  # ExprStmt
    | stmtBlock  # BlockStmt
    | 'return' expr ';'  # ReturnStmt
    | 'if' expr caseTrue=stmt ('else' caseFalse=stmt)?  # IfStmt
    | 'while' expr stmt  # WhileStmt
    ;

stmtBlock: '{' stmt* '}';

func: 'func' name=NAME '(' (arg=NAME ','?)* ')' body=stmtBlock;

query:
    'query' name=NAME
    'on' collection=NAME
    ('filter' filter=NAME)?
    ('map' map=NAME)?
    ('reduce' reduce=NAME)?
    ('limit' limit=INT)?
    ';';


// lexer rules
fragment DIGIT: [0-9];
fragment LETTER: [a-zA-Z_];
INT: DIGIT+;
STRING_LITERAL: '"'.*?'"';
NAME: LETTER(LETTER | DIGIT)*;
WS: [\t\r\n ]+ -> skip;
COMMENT: '/*' .*? '*/' -> skip;
LINE_COMMENT: '//' ~[\r\n]* -> skip;
