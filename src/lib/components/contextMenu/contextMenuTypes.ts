export interface ContextMenuItem {
	label: string;
	onClick: () => void;
	disabled?: boolean;
	separator?: boolean;
}

export interface ContextMenuEvent {
	items: ContextMenuItem[];
	x: number;
	y: number;
}

export type ContextMenuEventDetail = ContextMenuEvent;
