"""Frozen initial MySQL schema, recovered from 5b281bf before later revisions.

Revision 0001 must not import live ORM models: later columns belong to their own migrations.
Existing installations already past 0001 are unaffected.
"""
from alembic import op

revision = "20260219_0001"
down_revision = None
branch_labels = None
depends_on = None

INITIAL_STATEMENTS = (
    """CREATE TABLE app_settings (
	k VARCHAR(64) NOT NULL,
	v_json JSON NOT NULL,
	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (k)
)""",
    """CREATE TABLE roles (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(32) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name)
)""",
    """CREATE TABLE users (
	id BIGINT NOT NULL AUTO_INCREMENT,
	tg_user_id BIGINT NOT NULL,
	username VARCHAR(64),
	first_name VARCHAR(64),
	last_name VARCHAR(64),
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	UNIQUE (tg_user_id)
)""",
    """CREATE TABLE games (
	id BIGINT NOT NULL AUTO_INCREMENT,
	tg_group_id BIGINT NOT NULL,
	tg_topic_id BIGINT,
	status ENUM('LOBBY','RUNNING','ENDED') NOT NULL DEFAULT 'LOBBY',
	admin_user_id BIGINT NOT NULL,
	card_price BIGINT NOT NULL,
	sold_amount BIGINT NOT NULL DEFAULT '0',
	commission_rate DECIMAL(5, 4) NOT NULL DEFAULT '0.1000',
	commission_amount BIGINT NOT NULL DEFAULT '0',
	prize_pool BIGINT NOT NULL DEFAULT '0',
	col_prize_amount BIGINT NOT NULL DEFAULT '0',
	row_prize_amount BIGINT NOT NULL DEFAULT '0',
	prize_locked INTEGER NOT NULL DEFAULT '0',
	started_at TIMESTAMP NULL,
	ended_at TIMESTAMP NULL,
	col_paid INTEGER NOT NULL DEFAULT '0',
	payout_state_json JSON,
	row_winner_user_id BIGINT,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	FOREIGN KEY(admin_user_id) REFERENCES users (id),
	FOREIGN KEY(row_winner_user_id) REFERENCES users (id)
)""",
    """CREATE INDEX idx_group_status ON games (tg_group_id, status)""",
    """CREATE INDEX idx_group_topic_status ON games (tg_group_id, tg_topic_id, status)""",
    """CREATE TABLE user_roles (
	id BIGINT NOT NULL AUTO_INCREMENT,
	user_id BIGINT NOT NULL,
	role_id INTEGER NOT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	CONSTRAINT uq_user_role UNIQUE (user_id, role_id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(role_id) REFERENCES roles (id)
)""",
    """CREATE TABLE wallets (
	id BIGINT NOT NULL AUTO_INCREMENT,
	user_id BIGINT NOT NULL,
	balance BIGINT NOT NULL DEFAULT '0',
	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	UNIQUE (user_id),
	FOREIGN KEY(user_id) REFERENCES users (id)
)""",
    """CREATE TABLE game_called_numbers (
	id BIGINT NOT NULL AUTO_INCREMENT,
	game_id BIGINT NOT NULL,
	number INTEGER NOT NULL,
	called_by BIGINT NOT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	CONSTRAINT uq_game_number UNIQUE (game_id, number),
	FOREIGN KEY(game_id) REFERENCES games (id),
	FOREIGN KEY(called_by) REFERENCES users (id)
)""",
    """CREATE TABLE game_events (
	id BIGINT NOT NULL AUTO_INCREMENT,
	game_id BIGINT NOT NULL,
	tg_group_id BIGINT,
	kind ENUM('GAME_CREATED','CARDS_PURCHASED','GAME_STARTED','GAME_START_REJECTED','NUMBER_CALLED','NUMBER_UNDONE','PRIZE_COL','PRIZE_ROW','GAME_ENDED','GAME_LOBBY_CLOSED','ERROR') NOT NULL,
	actor_user_id BIGINT,
	idem_key VARCHAR(120),
	payload_json JSON,
	created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	FOREIGN KEY(game_id) REFERENCES games (id),
	FOREIGN KEY(actor_user_id) REFERENCES users (id)
)""",
    """CREATE TABLE wallet_txs (
	id BIGINT NOT NULL AUTO_INCREMENT,
	wallet_id BIGINT NOT NULL,
	direction ENUM('CREDIT','DEBIT') NOT NULL,
	amount BIGINT NOT NULL,
	reason ENUM('DEPOSIT_MANUAL','DEPOSIT_GATEWAY','DEPOSIT_CRYPTO','BUY_CARDS','PRIZE_COL','PRIZE_ROW','WITHDRAW','ADJUST') NOT NULL,
	ref_type VARCHAR(32),
	ref_id BIGINT,
	idempotency_key VARCHAR(80) NOT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	CONSTRAINT uq_wallet_idem UNIQUE (wallet_id, idempotency_key),
	FOREIGN KEY(wallet_id) REFERENCES wallets (id)
)""",
    """CREATE INDEX idx_wallet_created ON wallet_txs (wallet_id, created_at)""",
    """CREATE TABLE deposit_requests (
	id BIGINT NOT NULL AUTO_INCREMENT,
	user_id BIGINT NOT NULL,
	amount BIGINT NOT NULL,
	status ENUM('AWAITING_RECEIPT','PENDING_REVIEW','APPROVED','REJECTED') NOT NULL,
	receipt_file_id VARCHAR(255),
	receipt_path VARCHAR(255),
	reviewed_by BIGINT,
	reviewed_at TIMESTAMP NULL,
	wallet_tx_id BIGINT,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(reviewed_by) REFERENCES users (id),
	FOREIGN KEY(wallet_tx_id) REFERENCES wallet_txs (id)
)""",
    """CREATE TABLE game_purchases (
	id BIGINT NOT NULL AUTO_INCREMENT,
	game_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	qty INTEGER NOT NULL,
	unit_price BIGINT NOT NULL,
	total_price BIGINT NOT NULL,
	wallet_tx_id BIGINT NOT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	FOREIGN KEY(game_id) REFERENCES games (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(wallet_tx_id) REFERENCES wallet_txs (id)
)""",
    """CREATE INDEX idx_game_user ON game_purchases (game_id, user_id)""",
    """CREATE TABLE gateway_payments (
	id BIGINT NOT NULL AUTO_INCREMENT,
	user_id BIGINT NOT NULL,
	amount BIGINT NOT NULL,
	gateway VARCHAR(32) NOT NULL,
	authority VARCHAR(128),
	ref_id VARCHAR(128),
	status ENUM('CREATED','REDIRECTED','VERIFIED','FAILED') NOT NULL,
	wallet_tx_id BIGINT,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(wallet_tx_id) REFERENCES wallet_txs (id)
)""",
    """CREATE TABLE withdraw_requests (
	id BIGINT NOT NULL AUTO_INCREMENT,
	user_id BIGINT NOT NULL,
	amount BIGINT NOT NULL,
	full_name VARCHAR(128) NOT NULL,
	iban VARCHAR(34) NOT NULL,
	card_number VARCHAR(32) NOT NULL,
	account_number VARCHAR(32) NOT NULL,
	status ENUM('PENDING','APPROVED','PAID','REJECTED') NOT NULL,
	reviewed_by BIGINT,
	reviewed_at TIMESTAMP NULL,
	paid_tracking VARCHAR(128),
	wallet_tx_id BIGINT,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(reviewed_by) REFERENCES users (id),
	FOREIGN KEY(wallet_tx_id) REFERENCES wallet_txs (id)
)""",
    """CREATE TABLE game_cards (
	id BIGINT NOT NULL AUTO_INCREMENT,
	game_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	purchase_id BIGINT NOT NULL,
	numbers_json JSON NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id),
	CONSTRAINT uq_game_cards_game_fp UNIQUE (game_id, fingerprint),
	FOREIGN KEY(game_id) REFERENCES games (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(purchase_id) REFERENCES game_purchases (id)
)""",
    """CREATE INDEX idx_game_user ON game_cards (game_id, user_id)""",
)

def upgrade() -> None:
    for statement in INITIAL_STATEMENTS:
        op.execute(statement)

def downgrade() -> None:
    op.drop_table('game_cards')
    op.drop_table('withdraw_requests')
    op.drop_table('gateway_payments')
    op.drop_table('game_purchases')
    op.drop_table('deposit_requests')
    op.drop_table('wallet_txs')
    op.drop_table('game_events')
    op.drop_table('game_called_numbers')
    op.drop_table('wallets')
    op.drop_table('user_roles')
    op.drop_table('games')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('app_settings')
