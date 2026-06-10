-- ============================================================================
-- Migración 002: Arreglar error 500 al crear cuenta de paciente
-- ============================================================================
-- Problema:
--   POST /api/auth/register-init devolvía 500 con el error:
--     "null value in column 'activo' violates not-null constraint"
--   Las columnas `activo`, `suma_valoraciones` y `total_votos` eran NOT NULL
--   pero NO tenían DEFAULT, así que cualquier INSERT que no las indicara
--   fallaba — y el INSERT de register-init no las incluye.
--
-- Solución:
--   - Añadir DEFAULTs sensatos a las 3 columnas
--   - Sanear filas existentes con valores NULL
--   - Garantizar UNIQUE en correo_electronico
--
-- Cómo ejecutar:
--   Pegar en Supabase Dashboard → SQL Editor → Run.
--   Es idempotente: se puede ejecutar varias veces sin romper nada.
-- ============================================================================

-- 1) DEFAULTs en columnas NOT NULL ---------------------------------------------
ALTER TABLE usuarios ALTER COLUMN activo            SET DEFAULT TRUE;
ALTER TABLE usuarios ALTER COLUMN suma_valoraciones SET DEFAULT 0;
ALTER TABLE usuarios ALTER COLUMN total_votos       SET DEFAULT 0;

-- 2) Sanear filas existentes con NULL ------------------------------------------
UPDATE usuarios SET activo            = TRUE WHERE activo            IS NULL;
UPDATE usuarios SET suma_valoraciones = 0    WHERE suma_valoraciones IS NULL;
UPDATE usuarios SET total_votos       = 0    WHERE total_votos       IS NULL;

-- 3) UNIQUE en correo_electronico ----------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='usuarios_correo_key') THEN
        ALTER TABLE usuarios ADD CONSTRAINT usuarios_correo_key UNIQUE (correo_electronico);
    END IF;
EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE 'Hay correos duplicados, no se puede añadir UNIQUE';
END $$;
