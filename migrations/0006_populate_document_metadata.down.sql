-- Revert 0006: clear populated titles and published dates back to NULL.
SET search_path = public;

UPDATE documents
   SET title = NULL,
       published_date = NULL;
