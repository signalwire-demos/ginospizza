/**
 * PizzaRenderer - CSS layer stacking engine for visual pizza building.
 *
 * Each ingredient is an absolutely-positioned <img> inside a square container.
 * Z-index order: crust(10) -> sauce(20) -> cheese(30) -> toppings(40+) -> finish(90+)
 * Layers fade-in with slight scale on add, fade-out on remove.
 */
const PIZZA_SIZE_SCALE = {
    small: 0.70,
    medium: 0.85,
    large: 1.0,
};

class PizzaRenderer {
    constructor(container) {
        this.container = container;
        this.layers = new Map(); // key -> { element, data }
        this.locked = false;
        this.size = 'large';
    }

    /**
     * Set the pizza size and scale the canvas accordingly.
     */
    setSize(size) {
        this.size = size;
        const scale = PIZZA_SIZE_SCALE[size] || 1.0;
        this.container.style.transform = `scale(${scale})`;
        this.container.style.transformOrigin = 'center center';
    }

    /**
     * Generate a unique key for a layer.
     */
    _layerKey(data) {
        if (data.category === 'topping') {
            return `topping_${data.topping_name}_${data.placement || 'full'}`;
        }
        return data.category;
    }

    /**
     * Add a layer to the pizza.
     * @param {Object} data - { category, asset_path, z_index, label, topping_name?, placement? }
     */
    addLayer(data) {
        if (this.locked) return;

        const key = this._layerKey(data);

        // Remove existing layer of same key (e.g. replacing sauce)
        if (this.layers.has(key)) {
            this.removeLayerByKey(key, false);
        }

        const img = document.createElement('img');
        img.src = `/assets/${data.asset_path}`;
        img.alt = data.label || data.category;
        img.className = 'pizza-layer';
        img.style.zIndex = data.z_index || 10;
        img.draggable = false;

        // Start invisible for animation
        img.style.opacity = '0';
        img.style.transform = 'scale(0.9)';

        this.container.appendChild(img);

        // Trigger fade-in animation
        requestAnimationFrame(() => {
            img.style.opacity = '1';
            img.style.transform = 'scale(1)';
        });

        this.layers.set(key, { element: img, data: data });
    }

    /**
     * Remove a layer by key with optional animation.
     */
    removeLayerByKey(key, animate = true) {
        const layer = this.layers.get(key);
        if (!layer) return;

        if (animate) {
            layer.element.style.opacity = '0';
            layer.element.style.transform = 'scale(0.9)';
            setTimeout(() => {
                layer.element.remove();
            }, 300);
        } else {
            layer.element.remove();
        }

        this.layers.delete(key);
    }

    /**
     * Remove a topping layer by name.
     */
    removeTopping(toppingName) {
        // Remove all placements of this topping
        for (const [key, layer] of this.layers.entries()) {
            if (layer.data.category === 'topping' && layer.data.topping_name === toppingName) {
                this.removeLayerByKey(key, true);
            }
        }
    }

    /**
     * Remove a layer by category (for single-instance categories like crust, sauce, cheese).
     */
    removeCategory(category) {
        this.removeLayerByKey(category, true);
    }

    /**
     * Lock the renderer (pizza is complete).
     */
    lock() {
        this.locked = true;
        this.container.classList.add('pizza-locked');
    }

    /**
     * Unlock the renderer for modifications.
     */
    unlock() {
        this.locked = false;
        this.container.classList.remove('pizza-locked');
    }

    /**
     * Clear all layers.
     */
    clear() {
        for (const [key, layer] of this.layers.entries()) {
            layer.element.remove();
        }
        this.layers.clear();
        this.locked = false;
        this.container.classList.remove('pizza-locked');
    }

    /**
     * Build the pizza from a full layers array (for specialty pizzas).
     * @param {Array} layers - Array of layer data objects
     * @param {number} delay - Delay between layers in ms (for sequential reveal)
     */
    buildFromLayers(layers, delay = 200) {
        layers.forEach((layer, i) => {
            setTimeout(() => this.addLayer(layer), i * delay);
        });
    }
}
